#!/usr/bin/env python3
"""
Teste die MySQL Datenbankverbindung
"""
import mysql.connector
import os
from pathlib import Path

# .env laden
def load_env():
    env_path = Path(__file__).parent / '.env'
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key] = value

load_env()

# DB Config
MYSQL_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', ''),
    'database': os.getenv('DB_NAME', 'hue_monitoring')
}

def test_connection():
    """Teste MySQL Verbindung"""
    print("🔌 Teste MySQL Verbindung...")
    print(f"Host: {MYSQL_CONFIG['host']}")
    print(f"User: {MYSQL_CONFIG['user']}")
    print(f"Database: {MYSQL_CONFIG['database']}")
    print(f"Password: {'[gesetzt]' if MYSQL_CONFIG['password'] else '[leer]'}")
    print()
    
    try:
        # Verbindung testen
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        
        # MySQL Version
        cursor.execute("SELECT VERSION()")
        version = cursor.fetchone()[0]
        print(f"✅ Verbindung erfolgreich!")
        print(f"   MySQL Version: {version}")
        
        # Datenbank prüfen
        cursor.execute("SHOW DATABASES LIKE %s", (MYSQL_CONFIG['database'],))
        db_exists = cursor.fetchone()
        
        if db_exists:
            print(f"✅ Datenbank '{MYSQL_CONFIG['database']}' existiert")
            
            # Tabellen prüfen
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            print(f"   Tabellen: {[t[0] for t in tables] if tables else 'keine'}")
            
        else:
            print(f"❌ Datenbank '{MYSQL_CONFIG['database']}' existiert nicht")
            print("   Führe setup.sh aus oder erstelle sie manuell:")
            print(f"   sudo mysql -u root -e \"CREATE DATABASE {MYSQL_CONFIG['database']};\"")
        
        cursor.close()
        conn.close()
        
    except mysql.connector.Error as e:
        print(f"❌ Verbindungsfehler: {e}")
        print()
        print("🔧 Mögliche Lösungen:")
        print("1. MySQL installiert? sudo apt install mysql-server")
        print("2. MySQL läuft? sudo systemctl start mysql")
        print("3. Root Passwort? sudo mysql_secure_installation")
        print("4. Umgebungsvariablen korrekt? Check .env")
        
        return False
    
    return True

def create_tables():
    """Erstelle Tabellen falls sie nicht existieren"""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        
        print("\n📊 Erstelle Tabellen...")
        
        # Power log Tabelle
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS power_log (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                light_id VARCHAR(10) NOT NULL,
                light_name VARCHAR(100) NOT NULL,
                watts DECIMAL(5,2) NOT NULL,
                brightness INT NOT NULL,
                INDEX idx_timestamp (timestamp),
                INDEX idx_light_id (light_id)
            )
        """)
        print("✅ Tabelle 'power_log' erstellt")
        
        # Total consumption Tabelle  
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS total_consumption (
                id INT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                total_watts DECIMAL(7,2) NOT NULL,
                active_lights INT NOT NULL,
                INDEX idx_timestamp (timestamp)
            )
        """)
        print("✅ Tabelle 'total_consumption' erstellt")
        
        conn.commit()
        cursor.close()
        conn.close()
        
        print("✅ Alle Tabellen erfolgreich erstellt!")
        return True
        
    except Exception as e:
        print(f"❌ Fehler beim Erstellen der Tabellen: {e}")
        return False

def insert_test_data():
    """Füge Testdaten ein"""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor()
        
        print("\n🧪 Füge Testdaten ein...")
        
        # Test power log
        cursor.execute("""
            INSERT INTO power_log (timestamp, light_id, light_name, watts, brightness)
            VALUES (NOW(), '1', 'Test Licht', 5.5, 180)
        """)
        
        # Test total consumption
        cursor.execute("""
            INSERT INTO total_consumption (timestamp, total_watts, active_lights)
            VALUES (NOW(), 15.5, 3)
        """)
        
        conn.commit()
        
        # Daten lesen
        cursor.execute("SELECT COUNT(*) FROM power_log")
        power_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM total_consumption")
        total_count = cursor.fetchone()[0]
        
        print(f"✅ Testdaten eingefügt:")
        print(f"   power_log: {power_count} Einträge")
        print(f"   total_consumption: {total_count} Einträge")
        
        cursor.close()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"❌ Fehler bei Testdaten: {e}")
        return False

if __name__ == "__main__":
    print("🗄️ MySQL Datenbanktest für Hue Controller")
    print("=========================================")
    
    if test_connection():
        print("\n" + "="*40)
        
        create_choice = input("Tabellen erstellen? (y/N): ").lower()
        if create_choice == 'y':
            if create_tables():
                test_choice = input("Testdaten einfügen? (y/N): ").lower()
                if test_choice == 'y':
                    insert_test_data()
        
        print("\n✅ Test abgeschlossen!")
        print("   Du kannst jetzt den Hue Controller starten:")
        print("   python3 app.py")
        
    else:
        print("\n❌ Datenbanktest fehlgeschlagen!")
        print("   Behebe die Verbindungsprobleme und versuche es erneut.")
