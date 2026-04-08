# Guia Pas a Pas: Prova LAN – Indirect + Numbered

export PYTHONPATH="/home/milax/Escriptori/Task1/Prova1"

## Resum de l'escenari

Provaràs l'arquitectura **indirecta (RabbitMQ)** amb el model de **tickets numerats** entre múltiples màquines de la mateixa LAN.

### Rols de les màquines

| Rol | Què executa | Quantes? |
|-----|------------|----------|
| **Servidor** | Redis + RabbitMQ | **1** (centralitzat) |
| **Workers** | [indirect/worker.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/indirect/worker.py) | **1 o més** (escalable) |
| **Client** | [indirect/client.py](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/indirect/client.py) (benchmark) | **1** |

> [!IMPORTANT]
> El servidor de Redis i RabbitMQ ha de ser **Ubuntu** (el deploy.sh utilitza `apt-get` i `systemctl`). Les màquines de workers i client poden ser **Ubuntu o Windows**, però **Ubuntu és molt més recomanable** per evitar problemes de compatibilitat amb `pika` i signals.

---

## Pas 0: Preparació – Saber les IPs

A cada màquina, executa:

**Ubuntu:**
```bash
ip addr show | grep "inet "
# o bé:
hostname -I
```

**Windows:**
```powershell
ipconfig
```

Anota la IP de la LAN de cada màquina (ex: `192.168.1.X`). Comprova que les màquines es veuen entre elles:
```bash
ping 192.168.1.X
```

---

## Pas 1: Màquina Servidor (Ubuntu) – Instal·lar Redis + RabbitMQ

### 1.1 Instal·lar Redis

```bash
sudo apt-get update
sudo apt-get install -y redis-server
```

**Configurar Redis per acceptar connexions remotes:**
```bash
sudo nano /etc/redis/redis.conf
```
Canvia:
```diff
- bind 127.0.0.1 ::1
+ bind 0.0.0.0
```

Opcional però recomanat – desactiva el mode protegit:
```diff
- protected-mode yes
+ protected-mode no
```

Reinicia Redis:
```bash
sudo systemctl restart redis-server
sudo systemctl enable redis-server
```

Verifica:
```bash
redis-cli ping
# Ha de dir: PONG
```

### 1.2 Instal·lar RabbitMQ

```bash
sudo apt-get install -y rabbitmq-server
sudo systemctl start rabbitmq-server
sudo systemctl enable rabbitmq-server
```

**Configurar RabbitMQ per acceptar connexions remotes:**

Per defecte, l'usuari `guest` només pot connectar des de localhost. Has de crear un nou usuari o permetre guest remotament:

**Opció A – Crear un usuari nou (recomanat):**
```bash
sudo rabbitmqctl add_user ticket ticket123
sudo rabbitmqctl set_permissions -p / ticket ".*" ".*" ".*"
sudo rabbitmqctl set_user_tags ticket administrator
```

**Opció B – Permetre `guest` remotament:**
```bash
# Crea/edita el fitxer de configuració
sudo bash -c 'echo "loopback_users = none" > /etc/rabbitmq/rabbitmq.conf'
sudo systemctl restart rabbitmq-server
```

> [!TIP]
> Habilita el panell de gestió web per monitoritzar les cues:
> ```bash
> sudo rabbitmq-plugins enable rabbitmq_management
> ```
> Llavors pots accedir a `http://IP_SERVIDOR:15672` des del navegador.

### 1.3 Obrir els ports del firewall

```bash
sudo ufw allow 6379/tcp    # Redis
sudo ufw allow 5672/tcp    # RabbitMQ AMQP
sudo ufw allow 15672/tcp   # RabbitMQ Management (opcional)
```

### 1.4 Verificar connectivitat des d'una altra màquina

Des d'un client o worker:
```bash
# Testa Redis
redis-cli -h IP_SERVIDOR ping

# Testa RabbitMQ
python3 -c "
import pika
creds = pika.PlainCredentials('guest', 'guest')
conn = pika.BlockingConnection(pika.ConnectionParameters(host='IP_SERVIDOR', credentials=creds))
print('RabbitMQ OK')
conn.close()
"

#Si no va el pika fer el virtual environment
# Crear el venv
python3 -m venv ~/venv
# Activar-lo
source ~/venv/bin/activate
# Instal·lar totes les dependències
pip install pika redis
```

---

## Pas 2: Totes les màquines – Instal·lar Python i dependències

### Ubuntu:
```bash
sudo apt-get install -y python3 python3-pip python3-venv git
```

### Windows:
- Instal·la [Python 3.11+](https://www.python.org/downloads/) (marca "Add to PATH")

### Copiar el projecte a cada màquina

Copia la carpeta del projecte a cada màquina (USB, git, scp...):
```bash
# Exemple amb scp des de la teva màquina:
scp -r ./Prova1 user@IP_MAQUINA:~/Prova1
```

### Instal·lar dependències Python (a TOTES les màquines):
```bash
cd Prova1
pip install -r requirements.txt
```

---

## Pas 3: Generar el fitxer de benchmark (a la màquina Client)

```bash
cd Prova1
python benchmarks/generate.py
```

Això crea [benchmarks/benchmark_numbered.txt](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/benchmarks/benchmark_numbered.txt) (i unnumbered). Per la prova **numbered** només necessites el [benchmark_numbered.txt](file:///c:/Users/usuari/OneDrive%20-%20URV/Documentos/UNI/3r%20curs/Sistemes%20distribuits/Task1/Prova1/benchmarks/benchmark_numbered.txt).

> [!NOTE]
> Si vols alta contención:
> ```bash
> python benchmarks/generate.py --high-contention
> ```

---

## Pas 4: Netejar Redis (a la màquina Servidor)

Abans de cada prova, neteja les dades anteriors:
```bash
redis-cli -h localhost FLUSHDB
```

---

## Pas 5: Arrencar Workers (a les màquines Worker)

A cada màquina worker, configura les variables d'entorn per apuntar al servidor:

### Ubuntu:
```bash
export REDIS_HOST=IP_SERVIDOR
export RABBITMQ_HOST=IP_SERVIDOR
# Si has creat un usuari nou per RabbitMQ:
export RABBITMQ_USER=ticket
export RABBITMQ_PASS=ticket123
```

### Windows (PowerShell):
```powershell
$env:REDIS_HOST = "IP_SERVIDOR"
$env:RABBITMQ_HOST = "IP_SERVIDOR"
$env:RABBITMQ_USER = "ticket"
$env:RABBITMQ_PASS = "ticket123"
```

Arrencar els workers:
```bash
cd Prova1

# Pots arrencar múltiples workers per màquina:
python indirect/worker.py --worker-id w1 &
python indirect/worker.py --worker-id w2 &

# A Windows (obre terminals separades per cada un):
python indirect/worker.py --worker-id w1
```

Hauries de veure:
```
[w1] Waiting for requests (prefetch=10)…
```

> [!IMPORTANT]
> Si vols que el **servidor** també executi workers, pots fer-ho. En aquest cas les env vars serien `REDIS_HOST=localhost` i `RABBITMQ_HOST=localhost`.

---

## Pas 6: Executar el Benchmark (a la màquina Client)

Configura les variables d'entorn:
```bash
export REDIS_HOST=IP_SERVIDOR      # no cal si el client no accedeix a Redis directament
export RABBITMQ_HOST=IP_SERVIDOR
export RABBITMQ_USER=ticket
export RABBITMQ_PASS=ticket123
```

Executa el benchmark **numbered**:
```bash
cd Prova1

python indirect/client.py \
    --benchmark benchmarks/benchmark_numbered.txt \
    --output results_indirect_numbered.json \
    --timeout 300
```

Espera que acabi. Veuràs un resum com:
```
==================================================
  Total time:      X.XXX s
  Throughput:      XXXX ops/s
  Success:         XXXXX
  Rejected:        XXXXX
  Errors:          0
==================================================
```

---

## Pas 7: Verificar consistència

Des de la màquina servidor (o qualsevol amb accés a Redis):
```bash
redis-cli -h IP_SERVIDOR SCARD tickets:numbered:seats
```
El valor retornat hauria de coincidir amb el nombre de `Success` del benchmark i **mai superar 20.000**.

---

## Resum de què necessites instal·lar a cada màquina

| Màquina | SO recomanat | Instal·lar |
|---------|-------------|------------|
| **Servidor** | **Ubuntu** | Redis, RabbitMQ, Python 3.11+, pip deps |
| **Worker(s)** | Ubuntu (o Windows) | Python 3.11+, pip deps, codi del projecte |
| **Client** | Ubuntu (o Windows) | Python 3.11+, pip deps, codi del projecte + benchmark files |

---

## Esquema de xarxa

```
 Màquina Client                Màquina Servidor              Màquines Worker
┌─────────────┐               ┌──────────────┐              ┌──────────────┐
│ client.py   │──── AMQP ────▶│  RabbitMQ    │◀── AMQP ────│  worker.py   │
│ (benchmark) │               │  :5672       │              │  (w1, w2...) │
│             │               │              │              │              │
│             │               │  Redis       │◀── TCP ─────│  (accés a    │
│             │               │  :6379       │              │   Redis)     │
└─────────────┘               └──────────────┘              └──────────────┘
```

## Troubleshooting

| Problema | Solució |
|----------|---------|
| `Connection refused` a Redis | Verifica `bind 0.0.0.0` a redis.conf i reinicia |
| `Connection refused` a RabbitMQ | Verifica que el port 5672 està obert i el firewall permet |
| `ACCESS_REFUSED` a RabbitMQ | L'usuari `guest` no pot connectar remotament. Crea un usuari nou o configura `loopback_users = none` |
| Workers no processen | Comprova que apunten al `RABBITMQ_HOST` correcte |
| Resultats no arriben | Augmenta `--timeout`. Verifica que workers i client usen el mateix host RabbitMQ |
| `No module named 'pika'` | Executa `pip install -r requirements.txt` |
