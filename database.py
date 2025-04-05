import json
import os

CONFIG_FILE = "config.json"

def load_config():
    """تحميل الإعدادات من ملف config.json"""
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"لم يتم العثور على ملف {CONFIG_FILE}")
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    return config

def save_config(config):
    """حفظ الإعدادات إلى ملف config.json"""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

def update_section(section, key, value):
    """تحديث قيمة مفتاح معين في قسم من الإعدادات"""
    config = load_config()
    if section in config and key in config[section]:
        config[section][key] = value
        save_config(config)
        return True
    return False

def update_status(key, value):
    """تحديث حالة تشغيل البوت أو الخدمات"""
    config = load_config()
    if "status" in config and key in config["status"]:
        config["status"][key] = value
        save_config(config)
        return True
    return False