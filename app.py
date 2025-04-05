from flask import Flask, render_template, request, redirect, url_for, session, flash
import database

app = Flask(__name__)
app.secret_key = "سر_تشفير_عالي_المستوى"  # يجب تغييره في الإنتاج

# صفحة تسجيل الدخول
@app.route("/login", methods=["GET", "POST"])
def login():
    config = database.load_config()
    admin = config.get("admin", {})
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        if username == admin.get("username") and password == admin.get("password"):
            session["logged_in"] = True
            return redirect(url_for("dashboard"))
        else:
            flash("بيانات الدخول غير صحيحة", "danger")
    return render_template("login.html")

# صفحة لوحة التحكم الرئيسية
@app.route("/dashboard")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    config = database.load_config()
    return render_template("dashboard.html", config=config)

# حفظ التحديثات للإعدادات الرقمية
@app.route("/update/numeric", methods=["POST"])
def update_numeric():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    key = request.form.get("key")
    value = request.form.get("value")
    try:
        if "." in value:
            value = float(value)
        else:
            value = int(value)
    except:
        pass
    if database.update_section("numeric", key, value):
        flash(f"تم تحديث {key} بنجاح", "success")
    else:
        flash(f"حدث خطأ أثناء تحديث {key}", "danger")
    return redirect(url_for("dashboard"))

# حفظ التحديثات للإعدادات النصية
@app.route("/update/text", methods=["POST"])
def update_text():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    key = request.form.get("key")
    value = request.form.get("value")
    if database.update_section("text", key, value):
        flash(f"تم تحديث {key} بنجاح", "success")
    else:
        flash(f"حدث خطأ أثناء تحديث {key}", "danger")
    return redirect(url_for("dashboard"))

# تحديث حالة التشغيل
@app.route("/update/status", methods=["POST"])
def update_status():
    if not session.get("logged_in"):
        return redirect(url_for("login"))
    key = request.form.get("key")
    value = request.form.get("value")
    value = True if value.lower() == "true" else False
    if database.update_status(key, value):
        flash(f"تم تحديث حالة {key} بنجاح", "success")
    else:
        flash(f"حدث خطأ أثناء تحديث {key}", "danger")
    return redirect(url_for("dashboard"))

# تسجيل الخروج
@app.route("/logout")
def logout():
    session.pop("logged_in", None)
    return redirect(url_for("login"))

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)