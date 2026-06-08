# 🚀 Guía Paso a Paso – Despliegue en AWS Academy

## Requisitos Previos
- Acceso a **AWS Academy Learner Lab**
- Par de claves SSH (`.pem`) descargado

---

## PASO 1 – Crear la instancia EC2

1. Entra en **AWS Academy** → **Learner Lab** → **Start Lab** (botón verde)
2. Haz clic en **AWS** (cuando el indicador esté verde) para abrir la consola AWS
3. Ve a **EC2** → **Launch Instance**
4. Configura:
   - **Name**: `ticket-system`
   - **AMI**: Ubuntu Server 22.04 LTS (Free tier eligible)
   - **Instance type**: `t2.medium` (o `t2.micro` si no hay créditos, pero será más lento)
   - **Key pair**: Selecciona o crea una (descarga el `.pem`)
   - **Security Group**: Crea uno nuevo con estas reglas:
     | Type | Port | Source |
     |------|------|--------|
     | SSH | 22 | My IP |
     | Custom TCP | 8080 | Anywhere (0.0.0.0/0) |
     | Custom TCP | 8001-8010 | Anywhere |
     | Custom TCP | 5672 | Anywhere (RabbitMQ) |
     | Custom TCP | 15672 | Anywhere (RabbitMQ UI) |
     | Custom TCP | 6379 | Anywhere (Redis) |
5. Haz clic en **Launch Instance**
6. Espera a que el **Instance State** sea `Running`
7. Copia la **Public IPv4 address** (ej: `3.84.123.45`)

> 💡 Si quieres multi-VM, repite este paso para crear 2-3 instancias.

---

## PASO 2 – Conectar por SSH

```bash
# En tu terminal local (Linux/Mac):
chmod 400 keys.pem
ssh -i keys.pem ubuntu@98.86.110.43

# En Windows (PowerShell):
ssh -i keys.pem ubuntu@98.86.110.43

# En Windows (PuTTY):
# Convierte .pem a .ppk con PuTTYgen, luego conecta
```

---

## PASO 3 – Subir el proyecto a la VM

### Opción A: git clone (recomendado)
Si tienes el proyecto en un repositorio Git:
```bash
# En la VM:
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/TU_USUARIO/TU_REPO.git
cd TU_REPO
```

### Opción B: scp (copiar archivos)
```bash
# Desde tu PC local:
scp -i keys.pem -r "c:\Users\usuari\OneDrive - URV\Documentos\UNI\3r curs\Sistemes distribuits\Task1\Prova1\*" ubuntu@98.86.110.43:~/ticket-system/

# En la VM:
cd ~/ticket-system
```

### Opción C: FileZilla (interfaz gráfica)
1. Abre FileZilla → File → Site Manager
2. Protocol: SFTP, Host: `98.86.110.43`, User: `ubuntu`
3. Key file: tu `.pem`
4. Arrastra la carpeta `Prova1` a la VM

---

## PASO 4 – Instalar dependencias en la VM

```bash
# En la VM, dentro del directorio del proyecto:
cd ~/ticket-system   # o donde hayas subido los archivos

# Instalar Python, pip, Redis, RabbitMQ, NGINX
sudo apt-get update
sudo apt-get install -y python3 python3-pip python3-venv redis-server rabbitmq-server nginx curl

# Verificar servicios
redis-cli ping                    # Debe responder: PONG
sudo rabbitmqctl status | head -5 # Debe mostrar info de RabbitMQ

# Instalar dependencias Python
pip3 install -r requirements.txt
```

---

## PASO 5 – Usar benchmarks existentes

Si ya dispones de los ficheros de benchmark en la carpeta `benchmarks/`, no hace falta regenerarlos. Comprueba que existen y que contienen los archivos esperados:

```bash
# Desde el directorio del proyecto:
ls -la benchmarks/
# Debes ver (según lo que uses):
#   benchmark_unnumbered.txt
#   benchmark_numbered.txt
#   benchmark_numbered_highcont.txt  (si hiciste high-contention)
```

Si no tienes los ficheros en la VM, cópialos desde tu equipo local con `scp` o súbelos a la VM por SFTP/FileZilla. Ejemplo (PowerShell):

```powershell
# Copiar todo el directorio local benchmarks/ a la VM
scp -i .\keys.pem -r 'C:\ruta\a\benchmarks\*' ubuntu@<PUBLIC_IP>:~/ticket-system/benchmarks/
```

Si prefieres regenerarlos en la VM (opcional), el script está disponible en `benchmarks/generate.py` y puede ejecutarse así:

```bash
# Opcional: regenerar localmente en la VM (no es necesario si ya tienes los archivos)
python3 benchmarks/generate.py
python3 benchmarks/generate.py --high-contention
```

---

## PASO 6 – Ejecutar la Arquitectura DIRECTA (REST)

### 6.1 Arrancar servidores FastAPI
```bash
# Abrir múltiples terminales SSH o usar screen/tmux:
sudo apt-get install -y tmux

tmux new -s servers

# Servidor 1 (puerto 8001)
python3 -m uvicorn direct.server:app --host 0.0.0.0 --port 8001 &

# Servidor 2 (puerto 8002)
python3 -m uvicorn direct.server:app --host 0.0.0.0 --port 8002 &

# (Opcional) Servidor 3
python3 -m uvicorn direct.server:app --host 0.0.0.0 --port 8003 &

# Verificar que funcionan:
curl http://localhost:8001/health
curl http://localhost:8002/health
# Deben responder: {"status":"healthy"}
```

### 6.2 Configurar NGINX como Load Balancer
```bash
# Copiar la config de NGINX
sudo cp direct/nginx.conf /etc/nginx/conf.d/ticket_system.conf

# Eliminar la config por defecto (si interfiere)
sudo rm -f /etc/nginx/sites-enabled/default

# Verificar y recargar
sudo nginx -t
sudo systemctl reload nginx

# Probar el load balancer:
curl http://localhost:8080/health
# Debe responder: {"status":"healthy"}
```

### 6.3 Ejecutar benchmark DIRECTO
```bash
# Limpiar Redis antes de cada benchmark
redis-cli FLUSHDB

# Benchmark Unnumbered
python3 direct/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --url http://localhost:8080 \
    --concurrency 200 \
    --output results_direct_unnumbered.json

# Limpiar Redis
redis-cli FLUSHDB

# Benchmark Numbered
python3 direct/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --url http://localhost:8080 \
    --concurrency 200 \
    --output results_direct_numbered.json
```

---

## PASO 7 – Ejecutar la Arquitectura INDIRECTA (RabbitMQ)

> ℹ️ **Esta guía ejecuta todos los workers en UNA sola VM** (con `&`), que es lo
> más rápido para probar. Si tu entrega pide **un worker por máquina virtual**
> (broker central + N VMs worker), sigue **`GUIA_VM_WORKERS.md`** en su lugar:
> usa `scripts/deploy_broker.sh` + `scripts/deploy_worker.sh` y cada worker corre
> como servicio systemd en su propia VM.

### 7.1 Arrancar workers
```bash
# Worker 1
python3 indirect/worker.py --worker-id w1 --prefetch 10 &

# Worker 2
python3 indirect/worker.py --worker-id w2 --prefetch 10 &

# (Opcional) Más workers para probar escalabilidad
python3 indirect/worker.py --worker-id w3 --prefetch 10 &
python3 indirect/worker.py --worker-id w4 --prefetch 10 &
```

### 7.2 Ejecutar benchmark INDIRECTO
```bash
# Limpiar Redis
redis-cli FLUSHDB

# Benchmark Unnumbered
python3 indirect/client.py \
    --benchmark benchmarks/benchmark_unnumbered.txt \
    --output results_indirect_unnumbered.json

# Limpiar Redis
redis-cli FLUSHDB

# Benchmark Numbered
python3 indirect/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --output results_indirect_numbered.json
```

---

## PASO 8 – Generar gráficas

```bash
mkdir -p analysis/plots

python3 analysis/plot_results.py \
    --results \
        results_direct_unnumbered.json \
        results_direct_numbered.json \
        results_indirect_unnumbered.json \
        results_indirect_numbered.json \
    --output-dir analysis/plots

# Ver las gráficas generadas:
ls analysis/plots/
```

Para descargar las gráficas a tu PC:
```bash
# Desde tu PC local:
scp -i keys.pem ubuntu@98.86.110.43:~/ticket-system/analysis/plots/* .
```

---

## PASO 9 – Probar escalabilidad (más workers)

Repite los benchmarks variando el número de workers:

```bash
# Test con 1 worker
redis-cli FLUSHDB
# Mata workers anteriores y arranca solo 1
kill %2 %3 %4 2>/dev/null
python3 indirect/worker.py --worker-id w1 &
python3 indirect/client.py --benchmark benchmarks/benchmark_unnumbered.txt --output results_1w.json

# Test con 2 workers
redis-cli FLUSHDB
python3 indirect/worker.py --worker-id w2 &
python3 indirect/client.py --benchmark benchmarks/benchmark_unnumbered.txt --output results_2w.json

# Test con 4 workers
redis-cli FLUSHDB
python3 indirect/worker.py --worker-id w3 &
python3 indirect/worker.py --worker-id w4 &
python3 indirect/client.py --benchmark benchmarks/benchmark_unnumbered.txt --output results_4w.json

# Gráfica de escalabilidad
python3 analysis/plot_results.py \
    --scalability results_1w.json results_2w.json results_4w.json \
    --output-dir analysis/plots
```

---

## PASO 10 – Probar High Contention

```bash
redis-cli FLUSHDB

python3 direct/client.py \
    --benchmark benchmarks/benchmark_numbered_highcont.txt \
    --url http://localhost:8080 \
    --concurrency 200 \
    --output results_direct_highcont.json

redis-cli FLUSHDB

python3 indirect/client.py \
    --benchmark benchmarks/benchmark_numbered_highcont.txt \
    --output results_indirect_highcont.json
```

---

## 🔧 Troubleshooting

| Problema | Solución |
|----------|----------|
| `Connection refused` Redis | `sudo systemctl start redis-server` |
| `Connection refused` RabbitMQ | `sudo systemctl start rabbitmq-server` |
| NGINX `502 Bad Gateway` | Verifica que los servidores FastAPI están corriendo |
| `ModuleNotFoundError` | `pip3 install -r requirements.txt` |
| Permiso denegado `.pem` | `chmod 400 keys.pem` |
| Puerto bloqueado | Revisa Security Group en EC2 → Inbound Rules |

---

## ⚠️ IMPORTANTE – Al acabar

1. **Para los servicios** en la VM:
   ```bash
   kill $(jobs -p)   # Mata todos los procesos en background
   ```
2. **En AWS Academy**: Click **End Lab** para no gastar créditos
3. **Descarga** los resultados JSON y las gráficas antes de parar el lab
