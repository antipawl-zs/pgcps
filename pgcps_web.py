from flask import Flask, render_template, request
import os
import paramiko
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _load_dotenv_fallback(path=".env"):
    """Minimal .env loader if python-dotenv is not installed."""
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            os.environ.setdefault(key, value)


_load_dotenv_fallback()


def get_switch_profiles():
    """Return configured switch credential profiles from environment."""
    profiles = {}
    daclark_user = os.environ.get("SWITCH_USER_DACLARK", "").strip()
    daclark_pass = os.environ.get("SWITCH_PASS_DACLARK", "")
    if daclark_user and daclark_pass:
        profiles["daclark"] = {"username": daclark_user, "password": daclark_pass}

    admin_user = os.environ.get("SWITCH_USER_ADMIN", "").strip()
    admin_pass = os.environ.get("SWITCH_PASS_ADMIN", "")
    if admin_user and admin_pass:
        profiles["admin"] = {"username": admin_user, "password": admin_pass}

    return profiles


def resolve_credentials(profile_name, form_username, form_password):
    """Resolve SSH credentials from a stored profile or the submitted form."""
    profiles = get_switch_profiles()
    if profile_name and profile_name in profiles:
        return profiles[profile_name]["username"], profiles[profile_name]["password"]
    return form_username, form_password


def execute_command(ssh_client, command):
    stdin, stdout, stderr = ssh_client.exec_command(command)
    return stdout.read().decode("utf-8")


def get_up_interfaces(output):
    up_interfaces = []
    lines = output.splitlines()
    for line in lines:
        match = re.search(r"(\S+)\s+\S+\s+\S+\s+\S+\s+yes\s+up\s+\S+\s+\S+", line)
        if match:
            up_interfaces.append(match.group(1))
    return up_interfaces


def has_no_mac_address(output):
    return "No MAC entries found." in output


app = Flask(__name__)


@app.route("/")
def index():
    return render_template(
        "index.html",
        profiles=sorted(get_switch_profiles().keys()),
    )


@app.route("/check", methods=["POST"])
def check_interfaces():
    hostname = request.form["hostname"]
    profile = request.form.get("profile", "").strip()
    username, password = resolve_credentials(
        profile,
        request.form.get("username", ""),
        request.form.get("password", ""),
    )

    result = []

    if not username or not password:
        result.append("Missing credentials. Select a stored profile or enter username/password.")
        return render_template("result.html", result=result)

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(hostname, username=username, password=password)

        interface_output = execute_command(ssh, "show interface brief")
        up_interfaces = get_up_interfaces(interface_output)

        for interface in up_interfaces:
            mac_output = execute_command(ssh, f"show mac-address-table interface {interface}")
            if has_no_mac_address(mac_output):
                result.append(f"Interface {interface} is 'up' but has no MAC addresses.")

        if not result and up_interfaces:
            result.append(f"Checked {len(up_interfaces)} up interface(s); all have MAC entries.")
        elif not up_interfaces:
            result.append("No interfaces with status 'up' were found.")

        ssh.close()

    except Exception as e:
        result.append(f"An error occurred: {e}")

    return render_template("result.html", result=result)


if __name__ == "__main__":
    app.run(debug=True)
