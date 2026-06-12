# FortiGate MAC Enroller

A web application for managing and registering MAC addresses on FortiGate firewalls using a MariaDB database.

---

# 📥 Installation

## 1. Clone the Repository

```bash
git clone https://github.com/SLMAN-BLK/Fortigate-mac-enroller.git
cd Fortigate-mac-enroller
```

---

## 2. Configure the Environment

Copy the example environment file:

```bash
cp .env.example .env
```

Edit the configuration file:

```bash
vi .env
```

Update the variables according to your environment.

---

# 🗄️ MariaDB Installation

## Install MariaDB Server

```bash
sudo apt update
sudo apt install mariadb-server -y
```

## Start and Enable MariaDB

```bash
sudo systemctl start mariadb
sudo systemctl enable mariadb
sudo systemctl status mariadb
```

---

# ⚙️ MariaDB Configuration

Edit the MariaDB server configuration file:

```bash
sudo vi /etc/mysql/mariadb.conf.d/50-server.cnf
```

Change the bind address:

```ini
bind-address = 0.0.0.0
```

Restart MariaDB:

```bash
sudo systemctl restart mariadb
```

---

# 🧑‍💻 Database Setup

Connect to MariaDB:

```bash
sudo mysql
```

Create the database and user:

```sql
CREATE DATABASE `database-name`;

CREATE USER 'username'@'%' IDENTIFIED BY 'password';

GRANT ALL PRIVILEGES ON `database-name`.* TO 'username'@'%';

FLUSH PRIVILEGES;

EXIT;
```

---

# 🚀 Application Deployment

Run the deployment script:

```bash
chmod +x deploy.sh
./deploy.sh
```

Create the static directories:

```bash
cd /opt/mac-register

mkdir -p static/css
mkdir -p static/js
```

Restart the application service:

```bash
sudo systemctl restart mac-register
```

---

# 🐳 Docker Installation

A Docker image is available on Docker Hub.

For Docker deployment instructions, visit:

https://hub.docker.com/r/slmanblk/fortigate-mac-enroller

Follow the documentation provided on the Docker Hub page.

---

# 📌 Notes

* Never commit the `.env` file to GitHub.
* Use strong passwords for the MariaDB user account.
* Restrict database access whenever possible.
* Keep the application and database server updated.
