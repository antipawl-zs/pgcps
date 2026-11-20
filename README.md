# pgcps

Tools for PGCPS network checks, including Aruba switch inventory.

## Aruba switch inventory (nginx)

Scans three sites and serves counts/details on local nginx:

| Site | Abbreviation | Prefix |
|------|--------------|--------|
| Adelphi Elementary | ADELP | `10.1.x.x` |
| Bonnie F. Johns Admin | BFJ | `10.22.x.x` |
| Sasscer Admin | SAS | `10.159.x.x` |

### Requirements

- Reachability into site `10.x` networks (Aruba VIA / district VPN)
- Switch credentials in `.env` (see `.env.example`)

### Scan

```bash
./scan/run_scan.sh
# or
python3 scan/aruba_scan.py
```

Writes `www/data/inventory.json`.

### Serve

```bash
sudo cp nginx/switch-inventory.conf /etc/nginx/sites-available/switch-inventory.conf
sudo ln -sfn /etc/nginx/sites-available/switch-inventory.conf /etc/nginx/sites-enabled/switch-inventory.conf
sudo nginx -t && sudo nginx -s reload
```

Open [http://127.0.0.1:8080/](http://127.0.0.1:8080/).

### Security devices checker (Flask)

```bash
python3 pgcps_web.py
```
