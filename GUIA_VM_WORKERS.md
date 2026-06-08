# 🖥️ Guía – Un Worker por Máquina Virtual (AWS EC2)

Esta guía despliega la arquitectura **indirecta (RabbitMQ)** con **cada worker en
su propia VM**. La topología es:

```
                         ┌──────────────────────────┐
                         │   BROKER VM               │
   ┌──────────┐  AMQP    │   RabbitMQ :5672          │
   │ CLIENT VM│─────────▶│   Redis    :6379          │◀────┐
   │ client.py│◀─────────│   (estado + métricas)     │     │
   └──────────┘  results └──────────────────────────┘     │
                              ▲          ▲          ▲       │ Redis
                       AMQP   │          │          │ AMQP  │ (Lua atómico)
                    ┌─────────┘   ┌──────┘    ┌─────┘       │
              ┌───────────┐ ┌───────────┐ ┌───────────┐    │
              │ WORKER VM1│ │ WORKER VM2│ │ WORKER VM3│────┘
              │ worker.py │ │ worker.py │ │ worker.py │
              └───────────┘ └───────────┘ └───────────┘
```

- **1 Broker VM**: ejecuta Redis + RabbitMQ. Es el backend compartido.
- **N Worker VMs**: cada una ejecuta `indirect/worker.py` apuntando al broker.
  Cada VM se identifica por su *hostname* en las métricas (`by_node`), así que
  el gráfico de workers muestra la distribución real entre máquinas.
- **1 Client VM** (puede ser tu PC): publica el benchmark y lee resultados.

> ¿Por qué hace falta configuración extra? Por defecto **Redis solo escucha en
> `127.0.0.1`** y el usuario **`guest` de RabbitMQ está bloqueado para conexiones
> remotas**. `deploy_broker.sh` resuelve ambas cosas.

---

## Tus 4 VMs

En esta práctica usa estas IPs y estos roles:

| Rol | IP pública |
|-----|------------|
| Broker / Redis + RabbitMQ | `13.220.216.37` |
| Worker 1 | `18.209.162.85` |
| Worker 2 | `100.31.65.80` |
| Worker 3 | `3.87.18.80` |
| Worker 4 | `204.236.242.163` |

El flujo correcto es este:

1. Entrar por SSH en las 4 VMs.
2. Copiar el proyecto a cada VM.
3. Ejecutar `deploy_broker.sh` solo en la VM broker.
4. Ejecutar `deploy_worker.sh` una vez en cada worker.
5. Lanzar el benchmark desde la VM cliente o desde tu PC.

## PASO 1 – Crear las instancias EC2

Crea **4 instancias Ubuntu 22.04**: 1 broker y 3 workers. Para el client
puedes reutilizar tu PC o una instancia más.

**Security Group** (Inbound). Lo más simple es un único SG compartido que
permita todo el tráfico **dentro del propio grupo** + SSH/UI desde tu IP:

| Type        | Port  | Source                  | Para qué |
|-------------|-------|-------------------------|----------|
| SSH         | 22    | My IP                   | acceso   |
| Custom TCP  | 5672  | el propio Security Group| RabbitMQ (workers↔broker) |
| Custom TCP  | 6379  | el propio Security Group| Redis (workers↔broker) |
| Custom TCP  | 15672 | My IP                   | RabbitMQ UI (opcional) |

> 💡 Usa siempre las **IPs privadas** entre VMs (mismo VPC) — son más rápidas,
> gratuitas y no cambian al reiniciar como las públicas.

---

## PASO 2 – Subir el proyecto a TODAS las VMs (scp)

La forma más cómoda es copiar el código desde tu PC con `scp` (no necesitas que
el repo sea público). Desde **PowerShell**, en la carpeta del proyecto, sube a
las 4 VMs de golpe:

```powershell
cd "C:\Users\efren\OneDrive\Escriptori\Sistemes Distribuits\SD_Task1"

$ips = @("18.209.162.85","100.31.65.80","3.87.18.80","204.236.242.163","13.220.216.37")

foreach ($ip in $ips) {
    # 1) crear la carpeta destino en la VM
    ssh -i keys.pem -o StrictHostKeyChecking=no ubuntu@$ip "mkdir -p ~/ticket-system"

    # 2) copiar solo lo necesario (evita plots, results, Report.pdf, etc.)
    scp -i keys.pem -r `
        direct indirect shared scripts analysis benchmarks tests `
        requirements.txt requirements-dev.txt README.md `
        ubuntu@${ip}:~/ticket-system/

    # 3) marcar los scripts como ejecutables
    ssh -i keys.pem ubuntu@$ip "chmod +x ~/ticket-system/scripts/*.sh"
}
```

Notas:
- En PowerShell escribe **`${ip}:`** (con llaves): `$ip:` se interpretaría como
  un *scope* de variable. El backtick `` ` `` es la continuación de línea.
- Si OpenSSH se queja de permisos de `keys.pem`, restríngelos una vez:
  `icacls .\keys.pem /inheritance:r /grant:r "$env:USERNAME:(R)"`.
- Los scripts ya están en **LF**, así que no tendrás el error `bad interpreter:
  ^M`. Si alguna vez aparece, en la VM: `sed -i 's/\r$//' scripts/*.sh`.

El destino queda en `~/ticket-system` en cada VM.

> Alternativa con git: en cada VM, `sudo apt-get install -y git` y
> `git clone <tu-repo> ticket-system` (requiere que el repo sea accesible).
> También puedes usar FileZilla (SFTP) como en `GUIA_AWS_PASO_A_PASO.md`.

---

## PASO 3 – Configurar la BROKER VM

Abre la terminal SSH de la VM broker `13.220.216.37` y ejecuta este paso allí:

```bash
sudo ./scripts/deploy_broker.sh
```

Al terminar imprime su **IP privada** y los comandos exactos para los workers
y el cliente. Anota la IP (ej. `10.0.1.10`).

Credenciales por defecto: usuario RabbitMQ `ticket` / `ticket`, Redis sin
contraseña. Para cambiarlas:

```bash
sudo RABBITMQ_USER=miuser RABBITMQ_PASS=mipass REDIS_PASSWORD=miredis \
     ./scripts/deploy_broker.sh
```

Comprobar:
```bash
redis-cli -h 127.0.0.1 ping            # PONG
sudo rabbitmqctl list_users            # debe aparecer 'ticket'
```

---

## PASO 4 – Configurar cada WORKER VM

En **cada** VM worker (sustituye la IP por la del broker del paso 3):

```bash
sudo BROKER_HOST=10.0.1.10 ./scripts/deploy_worker.sh
```

Esto instala las dependencias, escribe `/etc/ticket-worker.env` apuntando al
broker, y arranca el worker como **servicio systemd** (`ticket-worker@1`) que
se reinicia solo si cae (tolerancia a fallos).

Si cambiaste credenciales en el broker, pásalas igual aquí:
```bash
sudo BROKER_HOST=10.0.1.10 \
     RABBITMQ_USER=miuser RABBITMQ_PASS=mipass REDIS_PASSWORD=miredis \
     ./scripts/deploy_worker.sh
```

Comprobar en la worker VM:
```bash
sudo systemctl status 'ticket-worker@*'
sudo journalctl -u 'ticket-worker@1' -f
# Debe mostrar: [<hostname>] Connected to RabbitMQ 10.0.1.10:5672 …
```

> Cada VM aparece con su **hostname** como `worker_id`. Para forzar un nombre:
> `sudo BROKER_HOST=… WORKER_ID=worker-1 ./scripts/deploy_worker.sh`.
> Para varios procesos en una misma VM: añade `INSTANCES=2`.

Repite el paso 4 una vez en cada worker VM:

1. SSH a `18.209.162.85` y ejecuta `deploy_worker.sh`.
2. SSH a `100.31.65.80` y ejecuta `deploy_worker.sh`.
3. SSH a `3.87.18.80` y ejecuta `deploy_worker.sh`.
4. SSH a `204.236.242.163` y ejecuta `deploy_worker.sh`.

**Añadir un worker = configurar una VM nueva**; RabbitMQ reparte la carga
automáticamente (fair dispatch).

---

## PASO 4-bis – Lanzar N workers de golpe (NO ir una a una)

No hace falta repetir el PASO 4 a mano en cada VM si usas `User Data` o una
AMI. Tienes dos formas de replicar workers:

### Opción A – User Data (recomendada: N VMs en un solo "Launch")

Cada instancia se auto-configura al arrancar.

1. Abre `scripts/worker_userdata.sh` y edita `BROKER_HOST` (IP privada del
   broker) y `REPO` (la URL de tu repositorio; debe ser accesible desde la VM).
2. EC2 → **Launch Instance**:
   - **Number of instances**: `N` (los que quieras)
   - **Advanced details → User data**: pega el contenido de
     `scripts/worker_userdata.sh`
3. **Launch**. Las N VMs clonan el proyecto y ejecutan `deploy_worker.sh` solas.

Comprobar (en cualquiera de ellas, tras ~1-2 min):
```bash
sudo tail -f /var/log/cloud-init-output.log     # progreso del arranque
sudo systemctl status 'ticket-worker@*'
```

### Opción B – AMI (imagen pre-configurada)

Si tu repo es privado o no quieres clonar en cada arranque:

1. Configura **una** worker VM con el PASO 4 y comprueba que el servicio corre.
2. EC2 → selecciona esa instancia → **Actions → Image and templates → Create
   image**. Espera a que la AMI esté `available`.
3. **Launch Instance** desde esa AMI con **Number of instances: N**.

Cada copia arranca con el código + el servicio ya instalados y se conecta al
broker automáticamente (el `WORKER_ID` = hostname hace que cada una sea un nodo
distinto). Si cambia la IP del broker, edita `/etc/ticket-worker.env` y
`sudo systemctl restart 'ticket-worker@*'`.

> 💡 La IP **privada** del broker no cambia mientras la VM siga encendida, así
> que la AMI/User Data siguen siendo válidos durante toda la sesión del lab.

---

## PASO 5 – Ejecutar el benchmark desde la CLIENT VM

En la VM cliente (o tu PC), apunta al broker y lanza el cliente:

```bash
cd ticket-system
export PYTHONPATH=$(pwd)
export RABBITMQ_HOST=<IP_PRIVADA_DEL_BROKER> REDIS_HOST=<IP_PRIVADA_DEL_BROKER>
export RABBITMQ_USER=ticket RABBITMQ_PASS=ticket
# export REDIS_PASSWORD=miredis   # solo si lo configuraste

python3 indirect/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --output results_indirect_unnumbered.json
```

La salida **SERVER-SIDE** muestra `Workers: N -> {hostname1: …, hostname2: …}`:
esa es la distribución real de carga **entre las VMs**.

> En el comando anterior, sustituye `<IP_PRIVADA_DEL_BROKER>` por la IP
> privada que te imprime `deploy_broker.sh`.

---

## PASO 6 – Escalabilidad (más workers = más VMs)

Para el gráfico throughput vs. nº de workers, repite el benchmark encendiendo/
apagando worker VMs (o sus servicios) entre ejecuciones:

```bash
# Apagar el worker de una VM concreta (SSH a esa VM):
sudo systemctl stop 'ticket-worker@1'
# Encenderlo de nuevo:
sudo systemctl start 'ticket-worker@1'
```

Lanza un benchmark por cada cantidad de VMs activas y guárdalo con nombre
distinto (`results_1w.json`, `results_2w.json`, …); luego:

```bash
python3 analysis/plot_results.py \
    --scalability results_1w.json results_2w.json results_4w.json \
    --output-dir analysis/plots
```

---

## PASO 7 – Tolerancia a fallos entre VMs

Con el benchmark corriendo, mata el worker de una VM:

```bash
# en una worker VM, a media ejecución:
sudo systemctl kill -s SIGKILL 'ticket-worker@1'
```

- RabbitMQ **reencola** los mensajes no confirmados a los workers supervivientes.
- systemd **reinicia** el proceso en 2 s; al reanudar, los mensajes redelivered
  se **deduplican** por `request_id` (no se vende dos veces el mismo ticket).
- En las métricas verás `replays > 0` y la carga desplazada a otras VMs.

---

## 🔧 Troubleshooting multi-VM

| Problema | Causa / Solución |
|----------|------------------|
| Worker no conecta a RabbitMQ | Usa el usuario `ticket` (NO `guest` — está bloqueado en remoto). Revisa `RABBITMQ_USER/PASS` en `/etc/ticket-worker.env`. |
| `Connection refused` a Redis/RabbitMQ | Falta abrir 6379/5672 en el Security Group **para el propio SG**, o usaste la IP pública en vez de la privada. |
| `by_node` muestra un solo nodo | Todos los workers comparten `WORKER_ID`. Deja el default (hostname) o pon uno distinto por VM. |
| Worker se reinicia en bucle | `sudo journalctl -u 'ticket-worker@1' -e` — suele ser `PYTHONPATH`/import o credenciales malas. |
| El cliente no lee métricas | Exporta `REDIS_HOST` (y `REDIS_PASSWORD` si aplica) en la VM cliente. |

## ⚠️ Al acabar

```bash
# en cada worker VM
sudo systemctl stop 'ticket-worker@*'
```
Y pulsa **End Lab** en AWS Academy para no gastar créditos.
