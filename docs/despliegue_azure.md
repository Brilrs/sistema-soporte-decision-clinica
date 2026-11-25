# Despliegue en Azure (Sprint 3, parte L)

Guía para levantar el CDSS en una sola máquina virtual de Azure, con datos sintéticos (decisiones 12
y 13 de `docs/plan_sprint3.md`). Está en el orden en que se ejecuta. Cada paso dice qué debe aparecer
al terminar.

| Decisión | Valor | Motivo |
| --- | --- | --- |
| Máquina | Una VM Ubuntu 24.04, Standard_B2ms (2 vCPU, 8 GiB; US$ 0,116 por hora encendida), con Docker Compose | La medida que se midió en el perfil B2ms (`docker-compose.b2ms.yml`) |
| Región | `chilecentral` (Chile Central) | La suscripción Azure for Students solo permite northcentralus, mexicocentral, eastus2, chilecentral y westus3; Chile Central es la más cercana a Perú (fila 154 de `cambios_respecto_al_OE2.md`) |
| PostgreSQL | PostgreSQL 16 en el contenedor `db` de la VM, con su volumen, y su respaldo diario a Blob | El servicio administrado del OE2 no cabe en el crédito de US$ 100 (fila 155) |
| Acceso web | HTTPS con el nombre que da Azure a la IP pública: `<etiqueta>.chilecentral.cloudapp.azure.com` (`CDSS_DOMINIO`) | Sin dominio propio |
| Secretos | Azure Key Vault, leído por la VM con su identidad administrada (`deploy/cargar_secretos.sh`) | Sin secretos en el repositorio ni en la línea de comandos |
| Encendido | La VM se enciende solo para desplegar, medir y probar, y se desasigna a mano (`az vm deallocate`) al terminar cada sesión. No hay apagado automático: no está disponible en Chile Central (paso 6, fila 160) | Cuidar el crédito |

Recursos que ya existen: el grupo de recursos `rg-cdss-anemia` (creado en brazilsouth; el grupo solo
guarda metadatos, los recursos nuevos van en chilecentral) y la cuenta de almacenamiento
`stcdssanemia2611` (Standard_LRS, chilecentral) con el contenedor `respaldos`.

## Archivos del despliegue

| Archivo | Qué hace |
| --- | --- |
| `docker-compose.prod.yml` | Se superpone a `docker-compose.yml`: solo Nginx publica puertos (80 y 443), reinicio automático, entorno de producción, certificado y límites de memoria |
| `frontend/nginx.prod.conf.template` | Nginx con HTTPS (TLS 1.2 y 1.3); el 80 solo sirve el desafío de Let's Encrypt y redirige al 443. Las reglas de la aplicación (`frontend/nginx/cdss_rutas.conf`) son las mismas de desarrollo |
| `deploy/despliegue.conf.ejemplo` | Configuración sin secretos (Key Vault, dominio, almacenamiento y retención). En la VM se copia como `deploy/despliegue.conf` |
| `deploy/cargar_secretos.sh` | Escribe `.env` (permisos 600) con los secretos de Key Vault |
| `deploy/aplicar_bd_vm.sh` | Aplica migraciones con el psql 16 de `postgres:16-alpine` en un contenedor (sin instalar psql en la VM) |
| `deploy/respaldo_pg.sh` y `deploy/restaurar_pg.sh` | Respaldo de PostgreSQL a Blob con retención, y su restauración (probada o real) |
| `deploy/respaldo_chroma.sh` y `deploy/probar_restauracion_chroma.sh` | Respaldo de ChromaDB y de las guías a Blob (`python -m app.respaldo`, parte K), y su restauración probada |
| `deploy/renovar_certificado.sh` | Emisión y renovación del certificado de Let's Encrypt (certbot en un contenedor) |
| `deploy/systemd/` | Temporizadores diarios de los respaldos y de la renovación del certificado |

Los scripts de `deploy/` se ejecutan con `bash deploy/<script>.sh` desde `/opt/cdss-anemia`.

## Presupuesto de memoria (VM de 8 GiB)

Límites de `docker-compose.prod.yml` (`mem_limit`). Son topes, no reservas. El uso medido sale de
`docs/mediciones_sprint2.md`, `jobs/README.md` y la parte J.

| Servicio | Desarrollo | Perfil B2ms (`docker-compose.b2ms.yml`) | Azure | Uso medido |
| --- | --- | --- | --- | --- |
| `modelos` | 5632 MiB | 4608 MiB | **3584 MiB** (antes 3072 MiB, fila 162) | de 1,76 a 2,05 GiB en consultas; hasta 2,3 GiB indexando con lote 8 (equipo de desarrollo). En la VM con 3072 MiB (25/11/2026): 2,985 GiB de 3 GiB en reposo; en el cgroup, `anon` 0,80 GiB y `file` 2,14 GiB (de ellos `file_mapped` 1,41 GiB: los modelos bge-m3 y el reranker ONNX mapeados), `memory.events` `max` 2419 y `oom_kill` 0, sin reinicios. No fue falta de memoria: el tope obligaba a expulsar y releer páginas de los modelos. Con 3584 MiB, al final de una corrida: `anon` 1,51 GiB, `file` 1,15 GiB y `max` 0; pico de 2264 MiB (`docs/mediciones_sprint3.md`) |
| `db` | 768 MiB | 768 MiB | **512 MiB** | unos 33 MiB |
| `chromadb` | 768 MiB | 512 MiB | **512 MiB** | de 66 a 103 MiB |
| `backend` | 512 MiB | 512 MiB | **512 MiB** | de 180 a 197 MiB |
| `indexador` | 768 MiB | sin límite propio | **512 MiB** | 86 MiB en espera; pico de 311 MiB |
| `nginx` | 64 MiB | 64 MiB | **64 MiB** | unos 6 MiB |
| **Permanentes** | 8512 MiB | | **5696 MiB** | |
| `jobs`, `respaldo` o `respaldo-guias` (uno a la vez, bajo demanda) | 768 MiB | 768 MiB | 768 MiB | |
| `certbot` (bajo demanda) | | | 128 MiB | |
| **Total con un trabajo bajo demanda** | | | **6464 MiB** | |

- Con un trabajo bajo demanda quedan unos **1,7 GiB** para Ubuntu, Docker y la caché de disco (8 GiB
  menos 6464 MiB son 1728 MiB, y Ubuntu ve algo menos de 8 GiB). Son topes: en la VM, los demás
  servicios usan mucho menos que su límite (columna «Uso medido»). Además se agrega un **archivo de swap de 2 GB** (paso 12), para que un pico no termine en un
  contenedor detenido por falta de memoria.
- `exportar-onnx` (6 GiB) y `descargar-modelos` (1 GiB) se ejecutan una sola vez, **con el resto del
  stack detenido** (paso 15).

## Secretos en Key Vault

Nombres de los secretos (sin valores) y la variable de `.env` que escribe `deploy/cargar_secretos.sh`.
Se revisaron contra `backend/app/core/config.py` (campos obligatorios) y contra las variables sin
valor por omisión de `docker-compose.yml` y `docker-compose.prod.yml`; una prueba
(`backend/tests/test_l_despliegue.py`) lo comprueba.

| Secreto | Variable | Para qué | Formato que exige el script |
| --- | --- | --- | --- |
| `postgres-password` | `POSTGRES_PASSWORD` | Superusuario `postgres` del contenedor `db` (solo para crear la base y migrar) | 16 o más caracteres, solo letras, números y `. _ ~ -` |
| `db-pwd-clinica` | `CDSS_DB_PWD_CLINICA` | Usuario `cdss_clinica` | Igual (va dentro de `DATABASE_URL_CLINICA`) |
| `db-pwd-generacion` | `CDSS_DB_PWD_GENERACION` | Usuario `cdss_generacion` | Igual |
| `db-pwd-admin` | `CDSS_DB_PWD_ADMIN` | Usuario `cdss_admin` | Igual |
| `db-pwd-auditor` | `CDSS_DB_PWD_AUDITOR` | Usuario `cdss_auditor` | Igual |
| `db-pwd-indexador` | `CDSS_DB_PWD_INDEXADOR` | Usuario `cdss_indexador` (indexador, jobs y respaldo) | Igual |
| `jwt-secreto` | `JWT_SECRETO` | Firma de los tokens de sesión | 32 o más caracteres |
| `clave-pii` | `CDSS_CLAVE_PII` | Cifrado de la identidad del paciente (pgcrypto). **Sin ella no se recupera la identidad: no se regenera nunca** | 32 o más caracteres |
| `clave-hmac` | `CDSS_CLAVE_HMAC` | HMAC del DNI y la historia clínica para buscarlos | 32 o más caracteres |
| `anthropic-api-key` | `ANTHROPIC_API_KEY` | API de Anthropic (componente de generación) | No vacío |
| `seed-contrasena` (opcional) | `SEED_CONTRASENA` | Contraseña inicial de las cuentas sintéticas de `seed_demo`; con `CDSS_SEED_EXIGIR_CAMBIO=true` cada cuenta debe cambiarla al ingresar | No vacío; al menos 10 caracteres con letras y números (política de contraseñas) |
| `blob-cadena-conexion` (opcional) | `AZURE_STORAGE_CONNECTION_STRING` | Solo si Blob no se usa con la identidad administrada (no hace falta en esta guía) | No vacío |

Ninguno lleva comillas simples ni saltos de línea. El script escribe además, sin secretos:
`COMPOSE_FILE=docker-compose.yml:docker-compose.prod.yml` (así basta con `docker compose up -d`),
`CDSS_DOMINIO`, `RESPALDO_CONTENEDOR_BLOB`, `AZURE_STORAGE_ACCOUNT_URL`, `CDSS_VERSION_CODIGO` (el
commit) y `CDSS_SEED_EXIGIR_CAMBIO=true`.

## Parte 1: recursos de Azure (PowerShell en su equipo)

Requisito: la [CLI de Azure](https://learn.microsoft.com/cli/azure/install-azure-cli-windows) instalada.
Abra **PowerShell** y deje la ventana abierta: los pasos usan las variables del paso 1.

### 1. Variables e inicio de sesión

```powershell
az login
az account show --query "{suscripcion:name, usuario:user.name}" -o table
$RG = "rg-cdss-anemia"
$LOC = "chilecentral"
$VM = "vm-cdss-anemia"
$ETIQUETA_DNS = "cdss-anemia-2611"
$KV = "kv-cdss-anemia-2611"
$ST = "stcdssanemia2611"
$USUARIO_VM = "cdssadmin"
$DOMINIO = "$ETIQUETA_DNS.$LOC.cloudapp.azure.com"
```

**Debe aparecer:** la suscripción «Azure for Students» y su usuario. Si la etiqueta DNS o el nombre
del Key Vault ya están en uso (error en los pasos 2 o 7), cambie el sufijo `2611` en las dos variables
y repita desde ese paso.

### 2. IP pública estática con etiqueta DNS

```powershell
az network public-ip create --resource-group $RG --name pip-cdss-anemia --location $LOC --sku Standard --allocation-method Static --version IPv4 --dns-name $ETIQUETA_DNS --output none
az network public-ip show --resource-group $RG --name pip-cdss-anemia --query "{ip:ipAddress, nombre:dnsSettings.fqdn}" -o table
```

**Debe aparecer:** una IP y el nombre `cdss-anemia-2611.chilecentral.cloudapp.azure.com`. La IP no
cambia al apagar y encender la VM.

### 3. Grupo de seguridad de red: SSH solo desde su IP, 80 y 443 abiertos

El 80 queda abierto solo porque Let's Encrypt valida el dominio por HTTP y para redirigir al 443:
Nginx no sirve la aplicación en el 80 (`frontend/nginx.prod.conf.template`). Las demás conexiones
entrantes desde internet quedan bloqueadas por la regla por defecto de Azure.

```powershell
az network nsg create --resource-group $RG --name nsg-cdss-anemia --location $LOC --output none
$MI_IP = (Invoke-RestMethod -Uri "https://api.ipify.org")
az network nsg rule create --resource-group $RG --nsg-name nsg-cdss-anemia --name permitir-ssh-mi-ip --priority 100 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes "$MI_IP/32" --source-port-ranges "*" --destination-port-ranges 22 --output none
az network nsg rule create --resource-group $RG --nsg-name nsg-cdss-anemia --name permitir-http-letsencrypt-y-redireccion --priority 110 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet --source-port-ranges "*" --destination-port-ranges 80 --output none
az network nsg rule create --resource-group $RG --nsg-name nsg-cdss-anemia --name permitir-https --priority 120 --direction Inbound --access Allow --protocol Tcp --source-address-prefixes Internet --source-port-ranges "*" --destination-port-ranges 443 --output none
az network nsg rule list --resource-group $RG --nsg-name nsg-cdss-anemia --query "[].{nombre:name, prioridad:priority, puerto:destinationPortRange, origen:sourceAddressPrefix}" -o table
```

**Debe aparecer:** las tres reglas; la de SSH con su IP y `/32`. Si su IP cambia (otra red), actualice
la regla:
`az network nsg rule update --resource-group $RG --nsg-name nsg-cdss-anemia --name permitir-ssh-mi-ip --source-address-prefixes "$((Invoke-RestMethod -Uri 'https://api.ipify.org'))/32" --output none`.

### 4. Red virtual

```powershell
az network vnet create --resource-group $RG --name vnet-cdss-anemia --location $LOC --address-prefixes 10.20.0.0/16 --subnet-name snet-cdss-anemia --subnet-prefixes 10.20.1.0/24 --output none
```

**Debe aparecer:** nada (sin error).

### 5. Máquina virtual con identidad administrada

```powershell
az vm create --resource-group $RG --name $VM --location $LOC --image Canonical:ubuntu-24_04-lts:server:latest --size Standard_B2ms --admin-username $USUARIO_VM --authentication-type ssh --generate-ssh-keys --public-ip-address pip-cdss-anemia --nsg nsg-cdss-anemia --vnet-name vnet-cdss-anemia --subnet snet-cdss-anemia --assign-identity --os-disk-name disco-cdss-anemia --os-disk-size-gb 64 --storage-sku StandardSSD_LRS --query "{estado:powerState, ip:publicIpAddress, nombre:fqdns}" -o table
$ID_VM = az vm show --resource-group $RG --name $VM --query identity.principalId -o tsv
$ID_VM
```

**Debe aparecer:** `VM running`, la IP del paso 2 y el nombre; luego el id de la identidad (un GUID).
La clave SSH queda en `C:\Users\<usted>\.ssh\id_rsa` (si ya existía, se reutiliza). El disco de 64 GB
alcanza para los modelos (unos 4,6 GB), las imágenes de Docker y los datos.

`az vm create` muestra además avisos informativos (sobre Trusted Launch y sobre la identidad asignada
sin `--scope`) que no hay que atender: la identidad recibe sus permisos en los pasos 7 y 9.

### 6. Sin apagado automático: apagar a mano

`az vm auto-shutdown` no funciona en Chile Central: el recurso que crea
(`Microsoft.DevTestLab/schedules`) no existe en esa región (`LocationNotAvailableForResourceType`),
debe estar en la región de la VM (`InvalidScheduleLocation` si se pide eastus2) y la región del grupo
de recursos, brazilsouth, no la permite la política de la suscripción (`RequestDisallowedByAzure`).
No hay apagado automático: **al terminar cada sesión**, apague la VM desde PowerShell:

```powershell
az vm deallocate --resource-group $RG --name $VM
```

Solo `deallocate` detiene el cobro del cómputo. Apagar desde Ubuntu (`sudo shutdown`) o con
`az vm stop` deja la VM detenida pero asignada, y se sigue cobrando. Detalle en «Apagar y encender la
VM».

### 7. Key Vault con permisos por rol

```powershell
az keyvault create --resource-group $RG --name $KV --location $LOC --enable-rbac-authorization true --retention-days 7 --output none
$ID_KV = az keyvault show --name $KV --query id -o tsv
$YO = az ad signed-in-user show --query id -o tsv
az role assignment create --assignee-object-id $YO --assignee-principal-type User --role "Key Vault Secrets Officer" --scope $ID_KV --output none
az role assignment create --assignee-object-id $ID_VM --assignee-principal-type ServicePrincipal --role "Key Vault Secrets User" --scope $ID_KV --output none
az role assignment list --scope $ID_KV --query "[].{rol:roleDefinitionName, tipo:principalType}" -o table
```

**Debe aparecer:** «Key Vault Secrets Officer» (User, usted: crea los secretos) y «Key Vault Secrets
User» (ServicePrincipal, la VM: solo los lee). Los permisos tardan hasta unos minutos en aplicarse: si
el paso 8 responde «Forbidden», espere 2 minutos y repítalo.

### 8. Secretos

Los valores se generan con el generador criptográfico de Windows y se pasan a la CLI por un archivo
temporal que se borra enseguida (no quedan en la pantalla ni en el historial). Un secreto que ya existe
**no se reemplaza** (sobre todo `clave-pii`: cambiarla haría ilegible la identidad cifrada).

```powershell
function New-SecretoHex { $b = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }
function Set-SecretoNuevo([string]$nombre, [string]$valor) {
  $existentes = @(az keyvault secret list --vault-name $KV --query "[].name" -o tsv)
  if ($existentes -contains $nombre) { Write-Host "$nombre ya existe: no se cambia"; return }
  $archivo = New-TemporaryFile
  try {
    Set-Content -Path $archivo -Value $valor -NoNewline -Encoding ascii
    az keyvault secret set --vault-name $KV --name $nombre --file $archivo --output none
    if ($LASTEXITCODE -eq 0) { Write-Host "$nombre creado" } else { Write-Host "ERROR al crear $nombre" }
  }
  finally { Remove-Item $archivo -Force }
}
foreach ($n in "postgres-password","db-pwd-clinica","db-pwd-generacion","db-pwd-admin","db-pwd-auditor","db-pwd-indexador","jwt-secreto","clave-pii","clave-hmac") { Set-SecretoNuevo $n (New-SecretoHex) }
$sufijo = (New-SecretoHex).Substring(0, 16)
Set-SecretoNuevo "seed-contrasena" "Cdss-$sufijo"
Remove-Variable sufijo
$clave = Read-Host "Pegue la clave de la API de Anthropic" -AsSecureString
Set-SecretoNuevo "anthropic-api-key" ([Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($clave)))
Remove-Variable clave
az keyvault secret list --vault-name $KV --query "[].name" -o tsv
```

La lista de secretos se pide con `--query "[].name"` y se compara en PowerShell: un filtro JMESPath
con paréntesis (`length([?name=='...'])`) pasa por cmd.exe en Windows y falla («No se esperaba -o en
este momento»), y la función creería que todos los secretos ya existen.

En la clave de Anthropic, el texto entre comillas de `Read-Host` es solo la etiqueta que se muestra:
pegue la clave después de los dos puntos que aparecen en pantalla, nunca dentro de las comillas.

**Debe aparecer:** «… creado» por cada secreto y, al final, los 11 nombres. Si aparece «ERROR al
crear ...», lea el mensaje de `az` que va antes (por ejemplo «Forbidden», paso 7) y vuelva a ejecutar
el bloque: los secretos ya creados no se cambian. La contraseña inicial de
las cuentas sintéticas se consulta solo cuando haga falta ingresar por primera vez:
`az keyvault secret show --vault-name $KV --name seed-contrasena --query value -o tsv`.

### 9. Permiso de la VM sobre el contenedor de respaldos

```powershell
$ID_ST = az storage account show --name $ST --query id -o tsv
az role assignment create --assignee-object-id $ID_VM --assignee-principal-type ServicePrincipal --role "Storage Blob Data Contributor" --scope "$ID_ST/blobServices/default/containers/respaldos" --output none
az role assignment list --scope "$ID_ST/blobServices/default/containers/respaldos" --query "[].roleDefinitionName" -o tsv
```

**Debe aparecer:** `Storage Blob Data Contributor`. La VM solo puede leer y escribir en el contenedor
`respaldos`, no en el resto de la cuenta.

### 10. Copiar las guías a la VM

Los PDF de las 4 guías de nivel 1 no están en el repositorio (`data/README.md`). Desde la carpeta del
proyecto en su equipo:

```powershell
cd C:\Users\Rbrill\ProyectosC\cdss-anemia
ssh "$USUARIO_VM@$DOMINIO" "mkdir -p ~/guias"
scp .\data\guias\*.pdf "${USUARIO_VM}@${DOMINIO}:~/guias/"
```

**Debe aparecer:** la primera vez, la pregunta «Are you sure you want to continue connecting» (responda
`yes`); luego los 4 PDF copiados.

## Parte 2: dentro de la VM (bash)

Entre por SSH: `ssh cdssadmin@cdss-anemia-2611.chilecentral.cloudapp.azure.com` (con el nombre de su
dominio). Los pasos siguientes se escriben en esa sesión.

### 11. Docker y herramientas

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
exit
```

Vuelva a entrar por SSH (el grupo `docker` se aplica en la sesión nueva) y compruebe:

```bash
docker compose version
```

**Debe aparecer:** `Docker Compose version v2...` (o superior).

### 12. Archivo de swap de 2 GB

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
echo 'vm.swappiness=10' | sudo tee /etc/sysctl.d/90-cdss-swap.conf
sudo sysctl --system > /dev/null
free -h
```

**Debe aparecer:** una fila `Swap:` con `2.0Gi`. Con `swappiness` 10 se usa solo ante un pico.

### 13. Código, configuración y modelos

Antes de clonar, el código de la parte L (`docker-compose.prod.yml`, `deploy/` y la configuración de
Nginx) debe estar fusionado en `main`: el clon toma `main`.

```bash
sudo mkdir -p /opt/cdss-anemia
sudo chown "$USER:$USER" /opt/cdss-anemia
git clone https://github.com/Brilrs/sistema-soporte-decision-clinica.git /opt/cdss-anemia
cd /opt/cdss-anemia
mkdir -p data/guias data/modelos data/respaldos data/mediciones
mv ~/guias/*.pdf data/guias/
cp deploy/despliegue.conf.ejemplo deploy/despliegue.conf
sed -i 's/^KEY_VAULT=.*/KEY_VAULT=kv-cdss-anemia-2611/; s/^CDSS_DOMINIO=.*/CDSS_DOMINIO=cdss-anemia-2611.chilecentral.cloudapp.azure.com/' deploy/despliegue.conf
grep -E '^(KEY_VAULT|CDSS_DOMINIO)=' deploy/despliegue.conf
```

Si el repositorio es privado, `git clone` pide usuario y contraseña: use su usuario de GitHub y un token
de acceso de solo lectura. Si cambió el sufijo `2611` en el paso 1, cámbielo también en el `sed`.

**Debe aparecer:** las dos líneas con su Key Vault y su dominio.

### 14. Secretos en `.env`

```bash
bash deploy/cargar_secretos.sh
ls -l .env
```

**Debe aparecer:** una línea `nombre: ok (VARIABLE)` por cada secreto (sin valores),
`blob-cadena-conexion: no existe (opcional...)`, `Escrito /opt/cdss-anemia/.env (permisos 600).` y
`-rw-------` en `ls`. Si dice «No se obtuvo el token de la identidad administrada», revise el paso 5;
si dice «Key Vault respondió 403», espere unos minutos (paso 7) y repita.

### 15. Modelos locales (una vez, con el stack detenido)

```bash
docker compose run --rm descargar-modelos
docker compose run --rm exportar-onnx
ls data/modelos/onnx
```

**Debe aparecer:** la descarga (unos 4,6 GB) y la exportación (unos 10 minutos; usa hasta 6 GiB, por
eso va antes de levantar el stack); al final, la carpeta `bge-reranker-v2-m3-int8`.

### 16. Imágenes y certificado

```bash
docker compose build
bash deploy/renovar_certificado.sh emitir
```

`emitir` detiene Nginx, deja que certbot valide el dominio en el puerto 80 y levanta Nginx (y con él
la base de datos, ChromaDB y el backend). La primera vez, el contenedor `db` crea el esquema, los
catálogos, los usuarios de conexión y las migraciones (`db/init`), con las contraseñas de `.env`.

**Debe aparecer:** `Successfully received certificate.` y `Certificado emitido para ... y Nginx
levantado.`

Nota: el nombre que da Azure (`cdss-anemia-2611.chilecentral.cloudapp.azure.com`, 48 caracteres) no
cabe en el `server_names_hash_bucket_size` por omisión de Nginx (64), y Nginx no arrancaba («could
not build server_names_hash, you should increase server_names_hash_bucket_size: 64»). La plantilla
`frontend/nginx.prod.conf.template` lo sube a 128 (fila 161). Si ve ese error, la imagen de Nginx
está construida con una plantilla anterior: actualice el código (`git pull`) y repita
`docker compose build nginx`.

### 17. Levantar todo y comprobar

```bash
docker compose up -d
docker compose ps
curl -sI "http://$(grep -oP '^CDSS_DOMINIO=\K.*' deploy/despliegue.conf)/" | head -3
curl -s "https://$(grep -oP '^CDSS_DOMINIO=\K.*' deploy/despliegue.conf)/api/salud"; echo
```

**Debe aparecer:** `db`, `backend`, `modelos` e `indexador` como `healthy` y `chromadb` y `nginx` como
`Up` (`modelos` tarda unos 3 minutos en calentar: repita `docker compose ps`); `HTTP/1.1 301 Moved
Permanently` con `Location: https://...`; y en `/api/salud`, `"estado":"ok"`.

### 18. Datos sintéticos y guías

```bash
docker compose exec backend python -m app.scripts.seed_demo
docker compose run --rm jobs python -m app.indexador cargar --manifiesto fuentes_iniciales.yaml
docker compose run --rm respaldo python -m app.respaldo verificar
```

**Debe aparecer:** los usuarios de prueba y los 10 pacientes ficticios (cada cuenta debe cambiar la
contraseña al ingresar: `CDSS_SEED_EXIGIR_CAMBIO=true`); las 4 guías indexadas; y «Coincide con
PostgreSQL». No hace falta `--permitir-no-verificadas`: las 22 transcripciones de
`backend/app/indexador/transcripciones` (rm251 y rm429) tienen `verificado_por` y
`fecha_verificacion`, y la versión 5 de las 4 guías se indexó sin esa opción (eventos GUIA_INDEXADA
del 13/11/2026 con 0 transcripciones no verificadas). No la use en la VM: si una transcripción nueva
quedara sin verificar, su guía de nivel 1 debe quedar en ERROR hasta completarla.

### 19. Respaldos y certificado programados

```bash
sudo cp deploy/systemd/cdss-* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now cdss-respaldo-pg.timer cdss-respaldo-chroma.timer cdss-certificado.timer
systemctl list-timers 'cdss-*'
```

**Debe aparecer:** los tres temporizadores con su próxima ejecución (03:00 y 03:30 en Lima los
respaldos, 04:00 y 16:00 la renovación). Con `Persistent=true`, si la VM estaba apagada a esa hora, se
ejecutan al encenderla (los scripts esperan a que el stack esté sano).

### 20. Primer respaldo y restauración probada

```bash
sudo systemctl start cdss-respaldo-pg.service
journalctl -u cdss-respaldo-pg -n 20 --no-pager
sudo systemctl start cdss-respaldo-chroma.service
journalctl -u cdss-respaldo-chroma -n 20 --no-pager
bash deploy/restaurar_pg.sh
bash deploy/probar_restauracion_chroma.sh
```

**Debe aparecer:**
- PostgreSQL: `Subido y comprobado: pg/cdss_AAAAMMDD_HHMMSS.dump (SHA-256 ...)`.
- ChromaDB: `Respaldo creado: respaldo_... (blob)` y «Coincide con PostgreSQL».
- `restaurar_pg.sh`: la tabla «cdss / restaurada» con las mismas tablas y `Restauración probada: ...`.
  Restaura en la base aparte `cdss_prueba_restauracion` y la borra; la base real no se toca.
- `probar_restauracion_chroma.sh`: la restauración en `guias_clinicas_prueba_restauracion`, «Las
  colecciones coinciden» y `Restauración probada: ...`; la colección de prueba se descarta.

### 21. Medir en la VM real

Mide los 12 casos de `backend/app/scripts/casos_e2e.yaml` por el grafo con la API real, una consulta
a la vez y con el calentamiento previo, igual que la corrida de referencia del 13/11/2026
(`docs/mediciones_sprint2.md`, «Corrida con el modelo real»). Requisitos: el stack levantado (paso
17), los datos sintéticos de `seed_demo` y las 4 guías indexadas (paso 18). Solo usa pacientes
ficticios de `seed_demo` (el script rechaza otro DNI). Cuesta unos US$ 0,25 (12 casos, 11 llamadas
al modelo) más unos US$ 0,025 de la consulta de calentamiento. Las consultas quedan registradas en la
base como consultas reales, igual que en las corridas anteriores. Mientras mide, nadie debe usar la
aplicación ni cargar guías.

Detalles del comando, comprobados en el código:
- El contenedor `backend` **no monta `data/mediciones`** (solo el volumen de las guías cargadas), y su
  usuario `cdss` no puede escribir en `/app`: sin un montaje, el script fallaría al guardar el
  informe, después de pagar las llamadas. Por eso la corrida usa `docker compose run` con
  `-v "$PWD/data/mediciones:/app/data/mediciones"` y `--user "$(id -u):$(id -g)"` (su usuario de la
  VM, dueño de la carpeta). No hace falta `docker cp`.
- Se usa la imagen `backend` y no `jobs`: la de `jobs` no tiene LangGraph.
- `ANTHROPIC_API_KEY` llega al contenedor desde `.env` (paso 14) por la variable del servicio
  `backend` de `docker-compose.yml`, sin escribirla en el comando. El script exige que exista y nunca
  la imprime. No ejecute `docker compose config` ni `env` dentro del contenedor: esos sí mostrarían los
  secretos.
- `docker-compose.prod.yml` fija `CDSS_LLM_FALSO_MODO=normal`, que es lo que exige `--llm real`.
- `--concurrentes 1` (una consulta a la vez) es el valor por omisión, pero se escribe explícito. El
  calentamiento de los modelos va incluido en el script (no se usa `--sin-calentar`).

**1. Antes de medir: estado del stack y consulta de calentamiento.** Después de encender la VM o de
levantar el sistema, la primera consulta tardó 38,5 s y las siguientes de 10,8 a 14,1 s (25/11/2026).
Por eso, antes de medir, se hace una consulta de calentamiento (caso `a`) que no se reporta. Su
informe va a `/tmp` dentro del contenedor y se pierde al terminar, como debe ser.

```bash
cd /opt/cdss-anemia
docker compose ps
free -h
docker compose run --rm --no-deps -T backend python -m app.scripts.medir_consulta --llm real --confirmo-datos-sinteticos --casos a --entorno vm_b2ms_real --etiqueta calentamiento --salida /tmp/calentamiento
```

**Debe aparecer:** en `docker compose ps`, `db`, `backend`, `modelos` e `indexador` como `healthy`
(si `modelos` dice `starting`, espere unos 3 minutos y repita). En `free -h`, la memoria usada y la
swap de 2,0 Gi. La consulta de calentamiento imprime una línea JSON que empieza por
`{"consultas": 1, "coinciden": 1, ...` y `Informe: /tmp/calentamiento/d_consulta_real_calentamiento.md`.
Si dice `--llm real exige ANTHROPIC_API_KEY`, el secreto no llegó a `.env`: repita el paso 14.

**2. Muestreo de memoria en segundo plano.** `backend/app/scripts/muestrear_memoria.py` (solo usa
Python y `docker stats`) guarda el pico de memoria y de CPU de cada contenedor hasta que aparece el
archivo `l_fin_medicion`:

```bash
rm -f data/mediciones/l_fin_medicion
python3 backend/app/scripts/muestrear_memoria.py --salida data/mediciones/l_memoria_azure_chilecentral.json --detener-si-existe data/mediciones/l_fin_medicion &
```

**Debe aparecer:** `[1]` y un número de proceso. No imprime nada más hasta que termina.

**3. La medición (unos 3 minutos).** Anote la hora de inicio y de fin (las pide el punto 6):

```bash
date
docker compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/data/mediciones:/app/data/mediciones" backend python -m app.scripts.medir_consulta --llm real --confirmo-datos-sinteticos --repeticiones 1 --concurrentes 1 --entorno vm_b2ms_real --etiqueta azure_chilecentral
date
touch data/mediciones/l_fin_medicion; wait; rm -f data/mediciones/l_fin_medicion
ls -l data/mediciones/
grep -c 'sk-ant' data/mediciones/d_consulta_real_azure_chilecentral.* data/mediciones/l_memoria_azure_chilecentral.json
```

**Debe aparecer:**
- Al terminar la medición, una línea JSON con el resumen (`"consultas": 12, "coinciden": 12, ...`) y
  `Informe: data/mediciones/d_consulta_real_azure_chilecentral.md`. El código de salida es 1 si algún
  caso no tuvo el estado esperado; el informe se guarda igual.
- Después de `wait`, `N muestras en S s: data/mediciones/l_memoria_azure_chilecentral.json`.
- En `ls`, los tres archivos: `d_consulta_real_azure_chilecentral.md`, `.json` y
  `l_memoria_azure_chilecentral.json`, con su usuario como dueño.
- En `grep`, un `:0` por archivo: ningún archivo contiene la clave de la API (la comprobación no
  imprime la clave).

**4. Las cifras para reportar:**

```bash
python3 - <<'PY'
import json
d = json.load(open("data/mediciones/d_consulta_real_azure_chilecentral.json", encoding="utf-8"))
r = d["resumen"]
con_modelo = sum(1 for c in d["consultas"] if any(i.get("modelo_llm") for i in c["intentos"]))
print("Total p50 / p90 / máx. (ms):", r["total_ms"]["p50"], r["total_ms"]["p90"], r["total_ms"]["max"])
print("Verificadas p50 / p90 (ms):", r["total_verificadas_ms"]["p50"], r["total_verificadas_ms"]["p90"])
print("Primer evento p50 / p90 (ms):", r["primer_evento_ms"]["p50"], r["primer_evento_ms"]["p90"])
print("Coinciden:", r["coinciden"], "de", r["consultas"])
for c in d["consultas"]:
    print(f'  caso {c["caso"]}: esperado {c["esperado"]}, obtenido {c["estado"]}, {c["total_cliente_ms"]} ms')
print("Intentos enviados:", r["intentos_enviados"], "| tokens de entrada / salida:", r["tokens_entrada"], r["tokens_salida"])
print("Costo total (USD):", r["costo_usd"], "| por consulta con llamada al modelo:", round(r["costo_usd"] / max(con_modelo, 1), 4), f"({con_modelo} consultas)")
print("Mediana por nodo (ms):", r["por_nodo_p50_ms"])
m = json.load(open("data/mediciones/l_memoria_azure_chilecentral.json", encoding="utf-8"))
for nombre, p in sorted(m["picos"].items()):
    print(f'  {nombre}: pico {p["mem_pico_mib"]} MiB de {p["limite_mib"]} MiB, CPU pico {p["cpu_pico_pct"]} %')
PY
free -h
```

**Debe aparecer:** las cifras y una línea por caso y por contenedor. Reporte:
- **Total** p50 y p90 (todas las consultas y las verificadas) y el máximo.
- **Primer evento** p50 y p90.
- **Estados de los 12 casos:** lo esperado es 9 VERIFICADA, 1 EVIDENCIA_INSUFICIENTE (caso j, con
  reintento), 1 DATOS_FALTANTES (g) y 1 FUERA_DE_DOMINIO (h), «Coinciden: 12 de 12».
- **Tokens** de entrada y de salida, y los intentos enviados (11 en la referencia).
- **Costo por consulta** con llamada al modelo (0,024 USD en la referencia; g y h no llaman al modelo).
- **Memoria máxima de `modelos`** (`cdss-anemia-modelos-1`; tope de 3584 MiB) y de los demás
  contenedores, más lo que muestra `free -h` (si se usó la swap).

**5. Comparar con el RNF3.** Según la propuesta de la fila 61 de `cambios_respecto_al_OE2.md`
(pendiente con el asesor): el primer evento con un p90 menor a 1 s, la respuesta completa con un p90
de **15 s o menos** en el flujo normal (las consultas VERIFICADA) y el caso j (con reintento) en 25 s
como máximo. Anote si se cumple cada uno. Compare además con la referencia del perfil normal (p90 de
las verificadas 12,54 s) y con el perfil B2ms simulado (18,92 s), ambos del 13/11/2026.

**6. Créditos de CPU de la VM.** La B2ms es de la familia B (burstable): acumula créditos mientras usa
poca CPU y los gasta cuando la usa por encima de su línea base. Si se queda sin créditos, Azure la
limita a esa línea base y las consultas se vuelven más lentas sin que nada lo indique dentro de la
VM. Para revisarlo, en el portal de Azure abra la VM `vm-cdss-anemia`, menú **Supervisión >
Métricas**, elija la métrica **CPU Credits Remaining** (agregación «Mínimo» o «Promedio») y ajuste
el intervalo de tiempo a la hora de la medición (anotada en el punto 3). También desde PowerShell en
su equipo (con las variables del paso 1; el intervalo en UTC, Lima más 5 horas):

```powershell
$ID_VM_RECURSO = az vm show --resource-group $RG --name $VM --query id -o tsv
az monitor metrics list --resource $ID_VM_RECURSO --metric "CPU Credits Remaining" --interval PT5M --aggregation Minimum --start-time 2026-11-25T20:00:00Z --end-time 2026-11-25T21:00:00Z -o table
```

Cambie las dos horas por las de su medición. **Debe aparecer:** una fila cada 5 minutos con los
créditos restantes. Si en algún momento de la medición llegan a **0**, anótelo en el informe junto a
las cifras (hora en que llegaron a 0 y cuántos quedaban al empezar): la medición se hizo con la CPU
limitada y no representa el funcionamiento normal. En ese caso, deje la VM encendida sin carga hasta
que recupere créditos y repita la medición. Si nunca llegan a 0, anote el mínimo.

**7. Copiar los resultados a su equipo** (PowerShell, desde la carpeta del proyecto):

```powershell
cd C:\Users\Rbrill\ProyectosC\cdss-anemia
scp "${USUARIO_VM}@${DOMINIO}:/opt/cdss-anemia/data/mediciones/d_consulta_real_azure_chilecentral.*" .\data\mediciones\
scp "${USUARIO_VM}@${DOMINIO}:/opt/cdss-anemia/data/mediciones/l_memoria_azure_chilecentral.json" .\data\mediciones\
```

**Debe aparecer:** los tres archivos copiados con su tamaño. Quedan en `data/mediciones/` de su
equipo (la carpeta no se sube a git). Al terminar, apague la VM (paso 6).

**8. Repetir con `modelos` en 3584 MiB (fila 162).** La primera medición en la VM se hizo con el
límite anterior de `modelos` (3072 MiB), que lo dejaba en el tope y releyendo páginas de los
modelos. Después de aplicar el cambio, repita los puntos 1 a 7 con otros nombres y compare los
contadores del cgroup de `modelos` con los de 3072 MiB (`anon` 861155328, `file` 2301599744,
`file_mapped` 1518669824, `max` 2419 y `oom_kill` 0):

```bash
cd /opt/cdss-anemia
git pull
docker compose up -d modelos
docker compose ps modelos
docker inspect --format '{{.HostConfig.Memory}}' cdss-anemia-modelos-1
```

**Debe aparecer:** `modelos` como `healthy` (repita `docker compose ps modelos` hasta que lo diga,
unos 3 minutos) y `3758096384` (3584 MiB en bytes). Después, la consulta de calentamiento del punto
1 y, con los nombres nuevos, el muestreo y la medición de los puntos 2 y 3:

```bash
rm -f data/mediciones/l_fin_medicion
python3 backend/app/scripts/muestrear_memoria.py --salida data/mediciones/l_memoria_azure_chilecentral_3584.json --detener-si-existe data/mediciones/l_fin_medicion &
docker compose run --rm --no-deps -T --user "$(id -u):$(id -g)" -e HOME=/tmp -v "$PWD/data/mediciones:/app/data/mediciones" backend python -m app.scripts.medir_consulta --llm real --confirmo-datos-sinteticos --repeticiones 1 --concurrentes 1 --entorno vm_b2ms_real --etiqueta azure_chilecentral_3584
touch data/mediciones/l_fin_medicion; wait; rm -f data/mediciones/l_fin_medicion
grep -c 'sk-ant' data/mediciones/d_consulta_real_azure_chilecentral_3584.* data/mediciones/l_memoria_azure_chilecentral_3584.json
```

En el bloque de cifras del punto 4, cambie los dos nombres de archivo por
`d_consulta_real_azure_chilecentral_3584.json` y `l_memoria_azure_chilecentral_3584.json`. Al
terminar, los contadores del cgroup de `modelos` (Ubuntu 24.04 usa cgroup v2; dentro del contenedor,
`/sys/fs/cgroup` es el cgroup del propio contenedor):

```bash
docker compose exec -T modelos sh -c 'grep -E "^(anon|file|file_mapped) " /sys/fs/cgroup/memory.stat; cat /sys/fs/cgroup/memory.events; cat /sys/fs/cgroup/memory.max'
docker inspect --format 'OOMKilled={{.State.OOMKilled}} reinicios={{.RestartCount}}' cdss-anemia-modelos-1
```

Si el primer comando no encuentra los archivos, léalos desde la VM:
`sudo cat /sys/fs/cgroup/system.slice/docker-$(docker inspect --format '{{.Id}}' cdss-anemia-modelos-1).scope/memory.events`
(y lo mismo con `memory.stat`).

**Debe aparecer:** las líneas `anon`, `file` y `file_mapped` en bytes; en `memory.events`, las
líneas `low`, `high`, `max`, `oom`, `oom_kill` (y `oom_group_kill`); `3758096384` en `memory.max`; y
`OOMKilled=false reinicios=0`. Compare con 3072 MiB: con el límite nuevo, `max` no debería seguir
subiendo durante la medición (`memory.events` cuenta desde que se creó el contenedor, así que anote
el valor antes y después de medir) y `oom_kill` debe seguir en 0. Copie los dos archivos nuevos con
el `scp` del punto 7, cambiando los nombres. Reporte las cifras de las dos mediciones, una al lado
de la otra.

## Restauración real

Solo ante una pérdida de datos. PostgreSQL primero, después ChromaDB del mismo día (el orden de
`docs/respaldo.md`):

```bash
cd /opt/cdss-anemia
bash deploy/restaurar_pg.sh pg/cdss_AAAAMMDD_HHMMSS.dump --sobre-cdss --confirmo
docker compose stop chromadb backend indexador
docker volume rm cdss-anemia_datos_chroma
docker compose up -d chromadb
docker compose run --rm respaldo-guias python -m app.respaldo restaurar respaldo_AAAAMMDD_HHMMSS --destino blob --con-guias
docker compose up -d
```

`restaurar_pg.sh` sin `--confirmo` se niega. Los nombres de los respaldos están en el contenedor
`respaldos` (en el portal de Azure, o con `bash deploy/restaurar_pg.sh` y
`bash deploy/probar_restauracion_chroma.sh`, que usan el más nuevo y lo muestran).

## Migraciones nuevas y actualizaciones

```bash
cd /opt/cdss-anemia
git pull
docker compose build
docker compose up -d
bash deploy/aplicar_bd_vm.sh --solo-migraciones
```

`aplicar_bd_vm.sh` corre `db/aplicar_bd.sh` con el psql 16 de `postgres:16-alpine` en un contenedor
conectado a la red del stack, sin instalar psql en la VM. Las contraseñas pasan al contenedor como
variables de entorno por nombre y psql las lee con `\getenv`: nunca aparecen en la línea de comandos
(`docs/mejoras_despliegue.md`).

**Debe aparecer:** `Aplicando 001_...` hasta la última migración y `Base de datos lista.`

## Apagar y encender la VM (cuidar el crédito)

No hay apagado automático (paso 6): apague la VM a mano al terminar cada sesión. Desde PowerShell en
su equipo (con las variables del paso 1):

```powershell
az vm deallocate --resource-group $RG --name $VM
az vm get-instance-view --resource-group $RG --name $VM --query "instanceView.statuses[1].displayStatus" -o tsv
```

**Debe aparecer:** `VM deallocated`. Desasignada no se cobra el cómputo (US$ 0,116 por hora); sí se
siguen cobrando el disco y la IP pública estática. `az vm stop` (sin desasignar) y el apagado desde
Ubuntu (`sudo shutdown`) **siguen cobrando** el cómputo: use siempre `deallocate`. No detenga los contenedores antes de apagar: con `restart:
unless-stopped`, los que quedaron en marcha vuelven solos al encender.

```powershell
az vm start --resource-group $RG --name $VM
az vm get-instance-view --resource-group $RG --name $VM --query "instanceView.statuses[1].displayStatus" -o tsv
ssh "$USUARIO_VM@$DOMINIO" "cd /opt/cdss-anemia && docker compose ps && systemctl list-timers 'cdss-*' --no-pager"
```

**Debe aparecer:** `VM running` y, en la VM, los servicios en marcha y los temporizadores.

**Consulta de calentamiento antes de medir o de abrir sesiones a usuarios.** Después de encender, la
primera consulta tardó 38,5 s y las siguientes de 10,8 a 14,1 s (25/11/2026). Cuando `modelos`
esté `healthy`, haga una consulta con un paciente ficticio de `seed_demo` (desde la aplicación, con
una cuenta de prueba) o con el comando de calentamiento del paso 21 (punto 1), y solo después mida o
avise a los usuarios.

**Qué se levanta solo al encender:**
- Docker (servicio habilitado en el paso 11).
- Los contenedores permanentes: `db`, `chromadb`, `modelos`, `backend`, `nginx` e `indexador`
  (`restart: unless-stopped`). `modelos` tarda unos 3 minutos en estar `healthy`; hasta entonces el
  backend responde, pero la primera consulta espera.
- Los temporizadores: si se perdió un respaldo o una renovación mientras estaba apagada, corren al
  encender (`Persistent=true`).

**Qué no se levanta (es bajo demanda):** `jobs`, `respaldo`, `respaldo-guias`, `certbot`,
`descargar-modelos` y `exportar-onnx`. Si antes de apagar se detuvo el stack con `docker compose
stop`, levántelo con `ssh "$USUARIO_VM@$DOMINIO" "cd /opt/cdss-anemia && docker compose up -d"`.

Si su IP cambió desde el paso 3, actualice la regla de SSH antes de entrar.

## Seguridad

- Solo Nginx publica puertos (80 y 443). PostgreSQL, ChromaDB, modelos y el backend quedan en la red
  interna de Docker; el grupo de seguridad solo deja entrar el 22 desde su IP, el 80 y el 443.
- TLS 1.2 y 1.3 (Let's Encrypt), HSTS de un año; el acceso por IP o con otro nombre se cierra sin
  responder. El 80 solo sirve el desafío de Let's Encrypt y redirige al 443.
- `.env` con permisos 600, escrito solo en la VM y regenerable desde Key Vault; nunca se sube al
  repositorio. Ningún script imprime valores de secretos ni los pasa en la línea de comandos.
- Solo datos sintéticos (decisión 12): `seed_demo` con cambio obligatorio de contraseña. El uso con
  pacientes reales requiere la autorización del asesor y de la institución.

## Qué no se probó sin Azure

Se probaron localmente: la configuración combinada (`docker compose config`), Nginx en modo producción
con un certificado autofirmado (redirección, desafío, TLS 1.1 rechazado, TLS 1.2 y 1.3 aceptados, SNI
de otro nombre rechazado), `db/aplicar_bd.sh` y `03_usuarios_bd.sh` con `\getenv` contra un PostgreSQL
16 desechable (usuarios que entran con su contraseña), y los scripts de `deploy/` con `curl` y `docker`
simulados (`backend/tests/test_l_despliegue.py`).

En Windows, esas pruebas necesitan Git Bash (`Git\bin\bash.exe`, que encuentran solas a partir de
`git`; nunca usan el `bash.exe` de system32, que es el de WSL). Sin Git Bash, se saltan con el motivo
«necesita Git Bash en Windows».

Quedan para la segunda mitad de la parte L, en Azure: la creación de los recursos, la identidad
administrada contra Key Vault y Blob, el certificado real de Let's Encrypt y su renovación, los
temporizadores de systemd, el apagado y encendido, HTTP/2 (el `curl` local no lo admite) y la medición
en la VM B2ms real.
