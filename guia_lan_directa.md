# Guia Pas a Pas: Prova LAN – Directa (REST) + Numbered

## Resum de l'escenari

Provaràs l'arquitectura **directa (REST/FastAPI)** amb el model de **tickets numerats** entre múltiples màquines de la mateixa LAN. **No cal RabbitMQ** per aquesta prova.

### Rols de les màquines

| Rol | Què executa | Quantes? |
|-----|------------|----------|
| **Servidor** | Redis | **1** (centralitzat) |
| **Servidors REST** | `uvicorn direct.server:app` | **1 o més** (escalable) |
| **Load Balancer** | NGINX (opcional) | **0 o 1** |
| **Client** | `direct/client.py` (benchmark) | **1** |

> [!NOTE]
> Els servidors REST poden córrer a la mateixa màquina que Redis o en màquines separades.

---

## Pas 0: Preparació – IPs

Anota la IP LAN de cada màquina:
```bash
# Ubuntu
hostname -I
# Windows
ipconfig
```

---

## Pas 1: Màquina Servidor (Ubuntu) – Redis

Si ja tens Redis instal·lat i configurat de la prova indirecta, **salta al Pas 2**.

Si no, segueix els mateixos passos que la guia indirecta:
```bash
sudo apt-get update
sudo apt-get install -y redis-server

# Editar per acceptar connexions remotes:
sudo nano /etc/redis/redis.conf
# Canvia: bind 0.0.0.0
# Canvia: protected-mode no

sudo systemctl restart redis-server
redis-cli ping   # Ha de dir PONG
```

---

## Pas 2: Màquina(es) dels Servidors REST – Preparar entorn

A cada màquina on vulguis arrencar servidors FastAPI:

```bash
# Crear venv (si no el tens)
python3 -m venv ~/venv
source ~/venv/bin/activate

# Copiar el projecte i instal·lar dependències
cd ~/Escriptori/Task1/Prova1    # o on tinguis el projecte
pip install -r requirements.txt
```

---

## Pas 3: Netejar Redis (abans de cada prova)

A la màquina del servidor Redis:
```bash
redis-cli FLUSHDB
```

---

## Pas 4: Arrencar Servidors REST

A cada màquina on vulguis executar servidors, configura les env vars i arrenca:

```bash
source ~/venv/bin/activate

# Apuntar al Redis del servidor
export REDIS_HOST="192.168.1.X"     # IP de la màquina amb Redis
export PYTHONPATH="/home/milax/Escriptori/Task1/Prova1"

cd ~/Escriptori/Task1/Prova1

# Arrenca 1 o 2 servidors per màquina:
python3 -m uvicorn direct.server:app --host 0.0.0.0 --port 8001 &
python3 -m uvicorn direct.server:app --host 0.0.0.0 --port 8002 &
```

Hauries de veure:
```
INFO:     Uvicorn running on http://0.0.0.0:8001
INFO:     Uvicorn running on http://0.0.0.0:8002
```

**Verifica** que funciona des d'una altra màquina:
```bash
curl http://192.168.1.Y:8001/health
# Ha de respondre: {"status":"healthy"}
```

---

## Pas 5 (Opcional): Configurar NGINX com a Load Balancer

Si vols repartir les peticions entre múltiples servidors/ports, instal·la NGINX a una de les màquines:

```bash
sudo apt-get install -y nginx
```

Edita la configuració:
```bash
sudo nano /etc/nginx/conf.d/ticket_system.conf
```

Posa:
```nginx
upstream ticket_backend {
    # Afegeix totes les IPs i ports dels teus servidors REST:
    server 192.168.1.Y:8001;
    server 192.168.1.Y:8002;
    # Si tens servidors a altres màquines:
    # server 192.168.1.Z:8001;
}

server {
    listen 8080;
    server_name _;

    proxy_connect_timeout 10s;
    proxy_read_timeout    30s;
    proxy_send_timeout    30s;

    location / {
        proxy_pass http://ticket_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_http_version 1.1;
    }
}
```

```bash
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t          # Ha de dir "ok"
sudo systemctl reload nginx
```

Verifica:
```bash
curl http://192.168.1.Y:8080/health
```

---

## Pas 6: Executar el Benchmark (màquina Client)

```bash
source ~/venv/bin/activate
export PYTHONPATH="/home/milax/Escriptori/Task1/Prova1"
cd ~/Escriptori/Task1/Prova1
```

### Sense NGINX (apuntant directament a un servidor):
```bash
python3 direct/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --url http://192.168.1.Y:8001 \
    --concurrency 200 \
    --output results_direct_numbered.json
```

### Amb NGINX (load balancer):
```bash
python3 direct/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --url http://192.168.1.Y:8080 \
    --concurrency 200 \
    --output results_direct_numbered.json
```

---

## Pas 7: Verificar consistència

```bash
redis-cli -h 192.168.1.X SCARD tickets:numbered:seats
```
Ha de coincidir amb el nombre de `Success` i **mai superar 20.000**.

---

## Esquema de xarxa

```
  Màquina Client              Màquina NGINX (opcional)         Màquines Servidor REST
┌─────────────┐              ┌──────────────┐                ┌──────────────┐
│ client.py   │── HTTP ─────▶│    NGINX     │── round-robin─▶│  uvicorn     │
│ (benchmark) │              │    :8080     │                │  :8001,:8002 │──┐
└─────────────┘              └──────────────┘                └──────────────┘  │
        │                                                                      │
        │  (o directe sense NGINX)                            Màquina Redis    │
        └──── HTTP ──────────────────────────────────────▶   ┌──────────────┐  │
                                                             │    Redis     │◀─┘
                                                             │    :6379    │
                                                             └──────────────┘
```

## Troubleshooting

| Problema | Solució |
|----------|---------|
| `Connection refused` al servidor REST | Verifica que uvicorn està corrent amb `--host 0.0.0.0` |
| `Connection refused` a Redis | Verifica `bind 0.0.0.0` a redis.conf |
| `502 Bad Gateway` a NGINX | Algun upstream server no està corrent. Comprova amb `curl` directe |
| `No module named 'shared'` | Falta `export PYTHONPATH="."` o el path del projecte |
| Errors molt alts al benchmark | Redueix `--concurrency` (prova amb 50 o 100) |
