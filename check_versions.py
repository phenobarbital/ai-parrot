
import urllib.request
import json
import ssl

def get_package_info(package_name):
    url = f"https://pypi.org/pypi/{package_name}/json"
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        with urllib.request.urlopen(url, context=ctx, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                releases = list(data["releases"].keys())
                releases.sort(key=lambda s: [int(u) for u in s.split('.') if u.isdigit()])
                print(f"Latest versions for {package_name}: {releases[-10:]}")
                latest_ver = releases[-1]
                latest_info = data["releases"][latest_ver][0]
                # Pypi JSON sometimes puts requires_dist in 'info' or in 'releases' items?
                # Actually it is in info usually for the *whole* package, but releases have specific info?
                # The endpoint /pypi/<name>/json returns 'info' for latest, and 'releases' map.
                # However, 'requires_dist' is often in 'info' (for latest) or check if release has it.
                print(f"Dependencies for {latest_ver}: {data['info'].get('requires_dist')}")
            else:
                print(f"Failed to find package {package_name}")
    except Exception as e:
        print(f"Error: {e}")

get_package_info("botbuilder-core")
