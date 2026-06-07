# Fortigate MAC Enroller

Application de gestion et d’enregistrement MAC pour FortiGate avec base de données MariaDB.

---

## 📥 Installation

### 1. Cloner le projet

```bash
git clone https://github.com/SLMAN-BLK/Fortigate-mac-enroller.git
cd Fortigate-mac-enroller
```

---

### 2. Configuration de l’environnement

Copier le fichier d’exemple `.env` :

```bash
cp .env.example .env
```

Modifier ensuite le fichier `.env` :

```bash
vi .env
```

---

## 🗄️ Installation de MariaDB

### Installer le serveur

```bash
sudo apt update
sudo apt install mariadb-server -y
```

### Démarrer et activer le service

```bash
sudo systemctl start mariadb
sudo systemctl enable mariadb
sudo systemctl status mariadb
```

---

## ⚙️ Configuration MariaDB

Éditer le fichier :

```bash
sudo vi /etc/mysql/mariadb.conf.d/50-server.cnf
```

Modifier la ligne :

```ini
bind-address = 0.0.0.0
```

Redémarrer MariaDB :

```bash
sudo systemctl restart mariadb
```

---

## 🧑‍💻 Création de la base de données et utilisateur

```bash
sudo mysql
```

```sql
CREATE DATABASE `database-name`;

CREATE USER 'username'@'%' IDENTIFIED BY 'password-of-the-user';

GRANT ALL PRIVILEGES ON `database-name`.* TO 'username'@'%';

FLUSH PRIVILEGES;

EXIT;
```

---

## 🚀 Déploiement de l’application

```bash
cd Fortigate-mac-enroller/
chmod +x deploy.sh
./deploy.sh

cd /opt/mac-register
mkdir static
cd static
mkdir css js
```

---

## 📌 Notes

- Ne jamais pousser le fichier `.env` sur GitHub
- Sécuriser l’accès MariaDB
