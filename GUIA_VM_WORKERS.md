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

## PASO 1 – Crear las instancias EC2

Crea **1 + N** instancias Ubuntu 22.04 (1 broker + N workers). Para el client
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

## PASO 2 – Subir el proyecto a TODAS las VMs

En cada VM (broker y workers):

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/TU_USUARIO/TU_REPO.git ticket-system
cd ticket-system
chmod +x scripts/*.sh
```

(o usa `scp`/FileZilla como en `GUIA_AWS_PASO_A_PASO.md`).

---

## PASO 3 – Configurar la BROKER VM

En la VM del broker:

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

Repite el paso 4 en cada worker VM. **Añadir un worker = configurar una VM
nueva**; RabbitMQ reparte la carga automáticamente (fair dispatch).

---

## PASO 5 – Ejecutar el benchmark desde la CLIENT VM

En la VM cliente (o tu PC), apunta al broker y lanza el cliente:

```bash
cd ticket-system
export PYTHONPATH=$(pwd)
export RABBITMQ_HOST=10.0.1.10 REDIS_HOST=10.0.1.10
export RABBITMQ_USER=ticket RABBITMQ_PASS=ticket
# export REDIS_PASSWORD=miredis   # solo si lo configuraste

python3 indirect/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --output results_indirect_unnumbered.json
```

La salida **SERVER-SIDE** muestra `Workers: N -> {hostname1: …, hostname2: …}`:
esa es la distribución real de carga **entre las VMs**.

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
