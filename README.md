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

---

# 📧 Email Notification Feature (Optional)

This section explains how to enable email notifications using **Postfix** as a local SMTP relay.

---

## 1. Install Postfix & mailutils

```bash
sudo apt update
sudo apt install postfix mailutils -y
```

> During installation, select **"Internet Site"** when prompted.

---

## 2. Configure Postfix

Open the Postfix main configuration file:

```bash
sudo vi /etc/postfix/main.cf
```

> ⚠️ **Important:** Remove any existing `relayhost` line before adding the block below to avoid duplicates.

Add the following at the end of the file:

```ini
relayhost = [smtp.your-provider.com]:587
smtp_use_tls = yes
smtp_sasl_auth_enable = yes
smtp_sasl_password_maps = hash:/etc/postfix/sasl_passwd
smtp_sasl_security_options = noanonymous
smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt
smtp_generic_maps = hash:/etc/postfix/generic
```

Replace `smtp.your-provider.com` with your actual SMTP relay host.

---

## 3. Configure Generic Address Mapping

Get your server hostname:

```bash
cat /etc/hostname
```

Create the generic map file:

```bash
sudo vi /etc/postfix/generic
```

Add the following line using your hostname and sender address:

```
root@your-hostname    sender@your-domain.com
```

Example:

```
root@ubuntu    notifications@example.com
```

Generate the hash:

```bash
sudo postmap /etc/postfix/generic
```

---

## 4. Configure SMTP Credentials

```bash
sudo vi /etc/postfix/sasl_passwd
```

Add your relay credentials:

```
[smtp.your-provider.com]:587    sender@your-domain.com:your-password
```

Secure the file and generate the hash:

```bash
sudo chmod 600 /etc/postfix/sasl_passwd
sudo postmap /etc/postfix/sasl_passwd
```

---

## 5. Restart & Verify Postfix

```bash
sudo systemctl restart postfix
sudo systemctl status postfix
```

> ⏳ Wait **2–3 minutes** before testing — Postfix needs time to fully initialize.

---

## 6. Test Email Sending

Basic test:

```bash
echo "hello world" | mail -s "Test Subject" recipient@example.com
```

With explicit sender:

```bash
echo "hello world" | mailx -s "Test Subject" -r "sender@your-domain.com" recipient@example.com
```

Monitor the mail logs in real time:

```bash
tail -f /var/log/mail.log
```

---

## 7. Enable the Email Feature in the Application

Switch to the email-enabled version of the app:

```bash
mv main.py main-no-emails.py
mv main-email-sending-fonction.py main.py
```

---

## 8. Set Sender & Recipient in the Application

Open `main.py` and update these two lines with your configured addresses:

```python
msg['From'] = "sender@your-domain.com"
msg['To'] = "recipient@your-domain.com"
```

Restart the service to apply the changes:

```bash
sudo systemctl restart mac-register
```
