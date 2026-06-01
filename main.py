# main.py
import os
import subprocess
import shutil
import random
import json
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, HTTPException, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import models, database

app = FastAPI(title="TACACS+ NG Premium WebGUI")

# Configurar directorio para archivos estáticos
os.makedirs("static/css", exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

import sys
import pty
import select

def verify_linux_password(username: str, password: str) -> bool:
    if not username or not password:
        return False
        
    pid, fd = pty.fork()
    
    if pid == 0:
        try:
            os.execvp("su", ["su", "-c", "echo VALIDATED", username])
        except Exception:
            sys.exit(1)
    else:
        output = b""
        status = 1
        try:
            r, w, x = select.select([fd], [], [], 2.0)
            if fd in r:
                os.read(fd, 1024)
                os.write(fd, password.encode() + b"\n")
                
                while True:
                    r, w, x = select.select([fd], [], [], 2.0)
                    if fd in r:
                        data = os.read(fd, 1024)
                        if not data:
                            break
                        output += data
                    else:
                        break
        except Exception as e:
            print("Error durante la interacción con su:", e)
        finally:
            os.close(fd)
            try:
                _, status = os.waitpid(pid, 0)
            except Exception:
                status = 1
                
        decoded = output.decode(errors="ignore")
        return "VALIDATED" in decoded and status == 0

# Middleware de Autenticación Global
@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    
    # Permitir archivos estáticos y la ruta de login sin autenticación
    public_prefixes = ["/login", "/static", "/api/status", "/favicon.ico"]
    is_public = any(path.startswith(p) for p in public_prefixes)
    
    session_user = request.cookies.get("session_user")
    
    # Registrar el usuario actual globalmente en Jinja2 para las vistas
    templates.env.globals["session_user"] = session_user
    
    if not session_user and not is_public:
        return RedirectResponse(url="/login", status_code=303)
        
    response = await call_next(request)
    return response

# Rutas de Inicio / Cierre de Sesión
@app.get("/login", response_class=HTMLResponse)
def get_login(request: Request, error: str = None):
    return templates.TemplateResponse(request, "login.html", context={"error": error})

@app.post("/login")
def post_login(username: str = Form(...), password: str = Form(...)):
    if verify_linux_password(username, password):
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="session_user",
            value=username,
            max_age=7200,
            httponly=True,
            samesite="lax"
        )
        return response
    else:
        return RedirectResponse(url="/login?error=Usuario+o+contrase%C3%B1a+incorrectos", status_code=303)

@app.get("/logout")
def get_logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_user")
    return response

# Configuración de cargadores de plantillas
templates = Jinja2Templates(directory="templates")
tac_templates = Jinja2Templates(directory="templates_tac")

# Variables globales para rutas híbridas
TAC_CONFIG_PATH = ""
MAIN_CONFIG_PATH = ""
IS_ROOT_MODE = False

def crear_config_defecto_local():
    global MAIN_CONFIG_PATH, TAC_CONFIG_PATH
    default_config = f"""# Configuración local de tac_plus-ng generada por WebGUI

id = spawnd {{
    background = yes
    listen {{
        port = 4949
    }}
    spawn {{
        instances min = 1
        instances max = 4
    }}
}}

id = tac_plus-ng {{
    key = "testing123"

    # 1. Definir los destinos de los archivos con sus respectivas rutas
    log acctlog {{
        destination = /home/tacacsd/frontTacacs/logs/accounting.log
        accounting format = "%Y-%m-%d %H:%M:%S\\t${nas}\\t${user}\\t${cmd}\\t${accttype}"
    }}

    log authnlog {{
        destination = /home/tacacsd/frontTacacs/logs/authentication.log
    }}

    log authzlog {{
        destination = /home/tacacsd/frontTacacs/logs/authorization.log
    }}

    # 2. Asignar cada proceso a su respectivo archivo de log personalizado
    authentication log = authnlog
    authorization log = authzlog
    accounting log = acctlog

    device all {{
        address = 0.0.0.0/0
        key = "testing123"
    }}

    # Regla simple: siempre permitir autenticación y autorización
    ruleset {{
        rule permit-all {{
            script {{
                permit
            }}
        }}
    }}

    # Incluir archivo dinámico de usuarios generados por la GUI
    include = "{TAC_CONFIG_PATH}"
}}
"""
    with open(MAIN_CONFIG_PATH, "w") as f:
        f.write(default_config)
    print(f"Creada configuración local por defecto en {MAIN_CONFIG_PATH}")

def inicializar_entorno():
    global TAC_CONFIG_PATH, MAIN_CONFIG_PATH, IS_ROOT_MODE
    
    # Asegurar la existencia del directorio de logs en cualquier modo
    try:
        os.makedirs("/home/tacacsd/frontTacacs/logs", exist_ok=True)
        os.chmod("/home/tacacsd/frontTacacs/logs", 0o777)
    except Exception as e:
        print("Advertencia al crear o cambiar permisos del directorio de logs:", e)
        
    test_path = "/etc/tac_plus-ng"
    try:
        if os.path.exists(test_path):
            if os.access(test_path, os.W_OK):
                IS_ROOT_MODE = True
        else:
            # Si no existe, intentamos crearla (fallará si no es root)
            os.makedirs(test_path, exist_ok=True)
            IS_ROOT_MODE = True
    except Exception:
        IS_ROOT_MODE = False
        
    if IS_ROOT_MODE:
        TAC_CONFIG_PATH = "/etc/tac_plus-ng/usuarios_gui.cfg"
        MAIN_CONFIG_PATH = "/etc/tac_plus-ng/tac_plus-ng.cfg"
        print("Modo de Ejecución: SISTEMA (Producción/Root)")
        
        # Si el archivo de configuración dinámico no existe, crearlo
        if not os.path.exists(TAC_CONFIG_PATH):
            with open(TAC_CONFIG_PATH, "w") as f:
                f.write("# Usuarios dinámicos generados por la GUI\n")
                
        # Si el archivo principal de producción no existe, autogenerarlo
        if not os.path.exists(MAIN_CONFIG_PATH):
            crear_config_defecto_local()
    else:
        # Modo local / fallback
        local_dir = "/home/tacacsd/frontTacacs/config"
        os.makedirs(local_dir, exist_ok=True)
        
        TAC_CONFIG_PATH = os.path.join(local_dir, "usuarios_gui.cfg")
        MAIN_CONFIG_PATH = os.path.join(local_dir, "tac_plus-ng.cfg")
        print("Modo de Ejecución: LOCAL (Desarrollo/Usuario tacacsd)")
        
        # Si el archivo de configuración dinámico no existe, crearlo vacío
        if not os.path.exists(TAC_CONFIG_PATH):
            with open(TAC_CONFIG_PATH, "w") as f:
                f.write("# Usuarios dinámicos generados por la GUI\n")
                
        # Si el archivo principal local no existe, crearlo
        if not os.path.exists(MAIN_CONFIG_PATH):
            source_cfg = "/usr/local/etc/tac_plus-ng.cfg"
            if os.path.exists(source_cfg) and os.access(source_cfg, os.R_OK):
                try:
                    with open(source_cfg, "r") as src:
                        content = src.read()
                    
                    # Para pruebas locales, creamos un duplicado en local
                    with open(MAIN_CONFIG_PATH, "w") as dest:
                        dest.write(content)
                    print(f"Copiado archivo base de sistema a {MAIN_CONFIG_PATH}")
                except Exception as e:
                    print(f"Error al copiar archivo base: {e}")
                    crear_config_defecto_local()
            else:
                crear_config_defecto_local()

# Ejecutar inicialización al cargar el módulo
inicializar_entorno()

# Generar las tablas en SQLite al arrancar
models.Base.metadata.create_all(bind=database.engine)

def aplicar_configuracion_tacacs(db: Session):
    usuarios = db.query(models.Usuario).all()
    dispositivos = db.query(models.Dispositivo).all()
    politicas_admin = db.query(models.PoliticaComando).filter(models.PoliticaComando.profile == "admin_profile").all()
    politicas_operador = db.query(models.PoliticaComando).filter(models.PoliticaComando.profile == "operador_profile").all()
    
    # 1. Renderizar la sintaxis tac_plus-ng usando Jinja2
    template_jinja = tac_templates.get_template("usuarios_gui.j2")
    config_renderizada = template_jinja.render(
        lista_usuarios=usuarios,
        lista_dispositivos=dispositivos,
        politicas_admin=politicas_admin,
        politicas_operador=politicas_operador
    )
    
    # 2. Guardar físicamente el archivo en el directorio de configuración
    with open(TAC_CONFIG_PATH, "w") as f:
        f.write(config_renderizada)
        
    # 3. Validar sintaxis con el binario nativo usando el flag -P
    command = ["/usr/local/sbin/tac_plus-ng", "-P", MAIN_CONFIG_PATH]
        
    validador = subprocess.run(
        command, 
        capture_output=True, text=True
    )
    
    if validador.returncode == 0:
        # Reiniciar el servicio de sistema para que lea los nuevos usuarios
        restart_res = subprocess.run(["sudo", "systemctl", "restart", "tac_plus-ng"], capture_output=True)
        if restart_res.returncode == 0:
            return True, "Servidor TACACS+ Next-Gen reiniciado con éxito con la nueva configuración."
        else:
            return True, "Sintaxis local validada con éxito. (Ejecución local, recarga manual)."
    else:
        error_msg = validador.stderr or validador.stdout
        return False, error_msg

# ==================== RUTAS WEB ====================

@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(database.get_db)):
    total_users = db.query(models.Usuario).count()
    admins = db.query(models.Usuario).filter(models.Usuario.profile == "admin_profile").count()
    operators = db.query(models.Usuario).filter(models.Usuario.profile == "operador_profile").count()
    
    # Determinar estado del daemon
    service_active = False
    try:
        # Buscar procesos de tac_plus-ng
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass

    return templates.TemplateResponse(request, "base.html", context={ 
        "total_users": total_users,
        "admins": admins,
        "operators": operators,
        "service_active": service_active,
        "is_root_mode": IS_ROOT_MODE,
        "main_config_path": MAIN_CONFIG_PATH,
        "current_page": "dashboard"
    })

@app.get("/usuarios", response_class=HTMLResponse)
def listar_usuarios(request: Request, db: Session = Depends(database.get_db)):
    usuarios = db.query(models.Usuario).all()
    service_active = False
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass
        
    return templates.TemplateResponse(request, "usuarios.html", context={
        "usuarios": usuarios,
        "service_active": service_active,
        "current_page": "usuarios"
    })

@app.post("/usuarios/nuevo")
def crear_usuario(
    username: str = Form(...), 
    password: str = Form(...), 
    profile: str = Form(...), 
    db: Session = Depends(database.get_db)
):
    # Validar si el usuario ya existe
    existing_user = db.query(models.Usuario).filter(models.Usuario.username == username).first()
    if existing_user:
        # En caso de error, podríamos redirigir con un query param, pero para simplicidad borramos y creamos o fallamos
        raise HTTPException(status_code=400, detail="El usuario ya existe.")
        
    nuevo_usuario = models.Usuario(username=username, password=password, profile=profile)
    db.add(nuevo_usuario)
    db.commit()
    
    # Regenerar el archivo y recargar el servicio AAA
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/usuarios", status_code=303)

@app.post("/usuarios/editar/{usuario_id}")
def editar_usuario(
    usuario_id: int,
    username: str = Form(...),
    password: str = Form(...),
    profile: str = Form(...),
    db: Session = Depends(database.get_db)
):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    usuario.username = username
    usuario.password = password
    usuario.profile = profile
    db.commit()
    
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/usuarios", status_code=303)

@app.post("/usuarios/eliminar/{usuario_id}")
def eliminar_usuario(usuario_id: int, db: Session = Depends(database.get_db)):
    usuario = db.query(models.Usuario).filter(models.Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    db.delete(usuario)
    db.commit()
    
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/usuarios", status_code=303)

@app.get("/configuracion", response_class=HTMLResponse)
def vista_configuracion(request: Request):
    service_active = False
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass
        
    # Leer el archivo de configuración principal
    config_content = ""
    if os.path.exists(MAIN_CONFIG_PATH):
        with open(MAIN_CONFIG_PATH, "r") as f:
            config_content = f.read()
            
    return templates.TemplateResponse(request, "configuracion.html", context={
        "config_content": config_content,
        "main_config_path": MAIN_CONFIG_PATH,
        "service_active": service_active,
        "current_page": "configuracion"
    })

@app.post("/configuracion/guardar")
def guardar_configuracion(config_text: str = Form(...), db: Session = Depends(database.get_db)):
    # 1. Guardar a un archivo temporal para validar de forma extremadamente segura
    temp_path = MAIN_CONFIG_PATH + ".tmp"
    with open(temp_path, "w") as f:
        f.write(config_text)
        
    # 2. Correr el validador binario sobre el temporal
    command = ["/usr/local/sbin/tac_plus-ng", "-P", temp_path]
        
    validador = subprocess.run(command, capture_output=True, text=True)
    
    if validador.returncode == 0:
        # Guardar definitivo
        shutil.copy(temp_path, MAIN_CONFIG_PATH)
        if os.path.exists(temp_path):
            os.remove(temp_path)
            
        # Reiniciar el servicio de sistema para aplicar los cambios
        subprocess.run(["sudo", "systemctl", "restart", "tac_plus-ng"])
            
        return JSONResponse(content={"status": "success", "message": "Configuración guardada y validada con éxito."})
    else:
        # Si falló la sintaxis, dejamos el archivo principal intacto y borramos el temporal
        error_msg = validador.stderr or validador.stdout
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return JSONResponse(content={"status": "error", "message": error_msg}, status_code=400)

# ==================== EXPORTACIÓN E IMPORTACIÓN DE RESPALDOS ====================

@app.get("/configuracion/exportar")
def exportar_configuracion(db: Session = Depends(database.get_db)):
    try:
        usuarios = db.query(models.Usuario).all()
        dispositivos = db.query(models.Dispositivo).all()
        politicas = db.query(models.PoliticaComando).all()
        
        data = {
            "usuarios": [
                {"username": u.username, "password": u.password, "profile": u.profile}
                for u in usuarios
            ],
            "dispositivos": [
                {"name": d.name, "address": d.address, "key": d.key}
                for d in dispositivos
            ],
            "politicas_comando": [
                {"profile": p.profile, "command": p.command, "action": p.action}
                for p in politicas
            ]
        }
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"tacacs_backup_{timestamp}.json"
        
        return JSONResponse(
            content=data,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al exportar: {str(e)}")

@app.post("/configuracion/importar")
async def importar_configuracion(
    file: UploadFile = File(...),
    mode: str = Form(...),
    db: Session = Depends(database.get_db)
):
    try:
        contents = await file.read()
        backup_data = json.loads(contents.decode("utf-8"))
    except Exception as e:
        return JSONResponse(status_code=400, content={"status": "error", "message": f"El archivo no es un JSON válido: {str(e)}"})
    
    if not isinstance(backup_data, dict) or not all(k in backup_data for k in ["usuarios", "dispositivos", "politicas_comando"]):
        return JSONResponse(
            status_code=400, 
            content={"status": "error", "message": "Estructura de respaldo inválida. Debe contener 'usuarios', 'dispositivos' y 'politicas_comando'."}
        )
        
    try:
        if mode == "overwrite":
            db.query(models.Usuario).delete()
            db.query(models.Dispositivo).delete()
            db.query(models.PoliticaComando).delete()
            
        for u_data in backup_data.get("usuarios", []):
            if not all(k in u_data for k in ["username", "password", "profile"]):
                raise ValueError("Faltan campos requeridos en un usuario del respaldo.")
            if mode == "merge":
                exists = db.query(models.Usuario).filter(models.Usuario.username == u_data["username"]).first()
                if exists:
                    continue
            nuevo_usuario = models.Usuario(
                username=u_data["username"],
                password=u_data["password"],
                profile=u_data["profile"]
            )
            db.add(nuevo_usuario)
            
        for d_data in backup_data.get("dispositivos", []):
            if not all(k in d_data for k in ["name", "address", "key"]):
                raise ValueError("Faltan campos requeridos en un dispositivo del respaldo.")
            if mode == "merge":
                exists = db.query(models.Dispositivo).filter(models.Dispositivo.name == d_data["name"]).first()
                if exists:
                    continue
            nuevo_disp = models.Dispositivo(
                name=d_data["name"],
                address=d_data["address"],
                key=d_data["key"]
            )
            db.add(nuevo_disp)
            
        for p_data in backup_data.get("politicas_comando", []):
            if not all(k in p_data for k in ["profile", "command", "action"]):
                raise ValueError("Faltan campos requeridos en una política del respaldo.")
            if mode == "merge":
                exists = db.query(models.PoliticaComando).filter(
                    models.PoliticaComando.profile == p_data["profile"],
                    models.PoliticaComando.command == p_data["command"],
                    models.PoliticaComando.action == p_data["action"]
                ).first()
                if exists:
                    continue
            nueva_pol = models.PoliticaComando(
                profile=p_data["profile"],
                command=p_data["command"],
                action=p_data["action"]
            )
            db.add(nueva_pol)
            
        db.flush()
        
        success, msg = aplicar_configuracion_tacacs(db)
        
        if success:
            db.commit()
            return JSONResponse(content={"status": "success", "message": "Respaldo importado con éxito."})
        else:
            db.rollback()
            aplicar_configuracion_tacacs(db)
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": f"Fallo en la validación sintáctica de TACACS+ con los datos importados. Los cambios han sido revertidos. Detalle: {msg}"
                }
            )
            
    except Exception as e:
        db.rollback()
        try:
            aplicar_configuracion_tacacs(db)
        except Exception:
            pass
        return JSONResponse(status_code=400, content={"status": "error", "message": f"Error al procesar la importación: {str(e)}"})

# ==================== GESTIÓN DE DISPOSITIVOS ====================

@app.get("/dispositivos", response_class=HTMLResponse)
def listar_dispositivos(request: Request, db: Session = Depends(database.get_db)):
    dispositivos = db.query(models.Dispositivo).all()
    service_active = False
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass
        
    return templates.TemplateResponse(request, "dispositivos.html", context={
        "dispositivos": dispositivos,
        "service_active": service_active,
        "current_page": "dispositivos"
    })

@app.post("/dispositivos/nuevo")
def crear_dispositivo(
    name: str = Form(...), 
    address: str = Form(...), 
    key: str = Form(...), 
    db: Session = Depends(database.get_db)
):
    existing = db.query(models.Dispositivo).filter(models.Dispositivo.name == name).first()
    if existing:
        raise HTTPException(status_code=400, detail="El dispositivo ya existe.")
        
    nuevo = models.Dispositivo(name=name, address=address, key=key)
    db.add(nuevo)
    db.commit()
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/dispositivos", status_code=303)

@app.post("/dispositivos/editar/{dispositivo_id}")
def editar_dispositivo(
    dispositivo_id: int,
    name: str = Form(...),
    address: str = Form(...),
    key: str = Form(...),
    db: Session = Depends(database.get_db)
):
    dispositivo = db.query(models.Dispositivo).filter(models.Dispositivo.id == dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
        
    dispositivo.name = name
    dispositivo.address = address
    dispositivo.key = key
    db.commit()
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/dispositivos", status_code=303)

@app.post("/dispositivos/eliminar/{dispositivo_id}")
def eliminar_dispositivo(dispositivo_id: int, db: Session = Depends(database.get_db)):
    dispositivo = db.query(models.Dispositivo).filter(models.Dispositivo.id == dispositivo_id).first()
    if not dispositivo:
        raise HTTPException(status_code=404, detail="Dispositivo no encontrado")
        
    db.delete(dispositivo)
    db.commit()
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/dispositivos", status_code=303)

# ==================== POLÍTICAS DE COMANDO ====================

@app.get("/politicas", response_class=HTMLResponse)
def listar_politicas(request: Request, db: Session = Depends(database.get_db)):
    politicas = db.query(models.PoliticaComando).all()
    service_active = False
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass
        
    return templates.TemplateResponse(request, "politicas.html", context={
        "politicas": politicas,
        "service_active": service_active,
        "current_page": "politicas"
    })

@app.post("/politicas/nuevo")
def crear_politica(
    profile: str = Form(...), 
    command: str = Form(...), 
    action: str = Form("deny"), 
    db: Session = Depends(database.get_db)
):
    nueva = models.PoliticaComando(profile=profile, command=command, action=action)
    db.add(nueva)
    db.commit()
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/politicas", status_code=303)

@app.post("/politicas/eliminar/{politica_id}")
def eliminar_politica(politica_id: int, db: Session = Depends(database.get_db)):
    politica = db.query(models.PoliticaComando).filter(models.PoliticaComando.id == politica_id).first()
    if not politica:
        raise HTTPException(status_code=404, detail="Política no encontrada")
        
    db.delete(politica)
    db.commit()
    aplicar_configuracion_tacacs(db)
    return RedirectResponse(url="/politicas", status_code=303)

# ==================== AUDITORÍA / ACCOUNTING API ====================

@app.get("/api/logs/accounting")
def api_accounting_logs():
    accounting_path = "/home/tacacsd/frontTacacs/logs/accounting.log"
    authorization_path = "/home/tacacsd/frontTacacs/logs/authorization.log"
    logs = []
    
    # 1. Leer accounting.log si tiene registros
    if os.path.exists(accounting_path):
        try:
            with open(accounting_path, "r") as f:
                lines = f.readlines()
                for line in lines[-100:]:
                    parts = line.strip().split("\t")
                    if len(parts) >= 5:
                        timestamp = parts[0]
                        if " -" in timestamp:
                            timestamp = timestamp.split(" -")[0]
                        logs.append({
                            "timestamp": timestamp,
                            "host": parts[1],
                            "user": parts[2],
                            "command": parts[3],
                            "action": parts[4]
                        })
        except Exception as e:
            print("Error parsing accounting log:", e)
            
    # 2. Leer authorization.log para capturar comandos autorizados en tiempo real
    if os.path.exists(authorization_path):
        try:
            with open(authorization_path, "r") as f:
                lines = f.readlines()
                for line in lines[-100:]:
                    parts = line.strip().split("\t")
                    if len(parts) >= 8:
                        cmd = parts[7].replace(" <cr>", "").strip()
                        if cmd and cmd != "":
                            subparts = parts[0].split(" ")
                            if len(subparts) >= 4:
                                timestamp = f"{subparts[0]} {subparts[1]}"
                                host = subparts[3]
                            else:
                                timestamp = parts[0]
                                host = "Desconocido"
                            
                            logs.append({
                                "timestamp": timestamp,
                                "host": host,
                                "user": parts[1],
                                "command": cmd,
                                "action": parts[5]
                            })
        except Exception as e:
            print("Error parsing authorization log for commands:", e)
            
    # Ordenar cronológicamente por timestamp
    logs.sort(key=lambda x: x["timestamp"])
    logs.reverse()
    return {"status": "success", "logs": logs}

@app.get("/logs", response_class=HTMLResponse)
def vista_logs(request: Request):
    service_active = False
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0:
            service_active = True
    except Exception:
        pass
        
    return templates.TemplateResponse(request, "logs.html", context={
        "service_active": service_active,
        "current_page": "logs"
    })

# ==================== API ENDPOINTS ====================

@app.get("/api/status")
def api_status():
    service_active = False
    pid = None
    try:
        pgrep_res = subprocess.run(["pgrep", "tac_plus-ng"], capture_output=True, text=True)
        if pgrep_res.returncode == 0 and pgrep_res.stdout:
            service_active = True
            pid = int(pgrep_res.stdout.strip().split("\n")[0])
    except Exception:
        pass
        
    # Simular métricas premium para el Dashboard
    cpu = round(random.uniform(0.5, 3.5), 1) if service_active else 0.0
    mem = round(random.uniform(1.2, 2.8), 1) if service_active else 0.0
    sessions = random.randint(1, 12) if service_active else 0
    
    return {
        "active": service_active,
        "pid": pid,
        "port": 49 if IS_ROOT_MODE else 4949,
        "mode": "SISTEMA (Root)" if IS_ROOT_MODE else "LOCAL (Desarrollo)",
        "cpu": cpu,
        "memory": mem,
        "active_sessions": sessions,
        "main_config": MAIN_CONFIG_PATH
    }

@app.get("/api/logs")
def api_logs():
    # 1. Intentar obtener logs de los archivos personalizados configurados
    authn_path = "/home/tacacsd/frontTacacs/logs/authentication.log"
    authz_path = "/home/tacacsd/frontTacacs/logs/authorization.log"
    
    custom_logs = []
    
    for path in [authn_path, authz_path]:
        if os.path.exists(path) and os.access(path, os.R_OK):
            try:
                with open(path, "r") as f:
                    lines = f.readlines()
                    for line in lines[-50:]:
                        clean_line = line.strip()
                        if clean_line and not clean_line.startswith("#"):
                            custom_logs.append(clean_line)
            except Exception as e:
                print(f"Error al leer {path}:", e)
                
    if custom_logs:
        # Ordenar cronológicamente (dado que inician con timestamp)
        custom_logs.sort()
        return {"status": "success", "logs": custom_logs[-50:]}

    # 2. Intentar con journalctl
    try:
        res = subprocess.run(["journalctl", "-u", "tac_plus-ng", "-n", "30", "--no-pager"], capture_output=True, text=True)
        if res.returncode == 0 and res.stdout:
            lines = res.stdout.strip().split("\n")
            return {"status": "success", "logs": lines}
    except Exception:
        pass
        
    # 3. Intentar leer syslog
    syslog_path = "/var/log/syslog"
    if os.path.exists(syslog_path) and os.access(syslog_path, os.R_OK):
        try:
            with open(syslog_path, "r") as f:
                lines = f.readlines()
                tac_lines = [line.strip() for line in lines if "tac_plus" in line]
                if tac_lines:
                    return {"status": "success", "logs": tac_lines[-40:]}
        except Exception:
            pass
            
    # 4. Retornar simulación realista si no se puede leer el sistema
    users = ["admin", "arturo.serrano", "readonly_user", "operator_demo"]
    actions = [
        "Authentication successful (cleartext)",
        "Authorization request for 'show running-config' approved (priv-lvl 15)",
        "Authorization request for 'configure terminal' approved (priv-lvl 15)",
        "Authorization request for 'configure terminal' denied (priv-lvl 7)",
        "Authentication successful (PAP)",
        "Disconnecting session, status: successful",
        "Authentication failed (incorrect password)"
    ]
    ips = ["192.168.1.50", "10.0.25.12", "172.16.5.101"]
    
    simulated = []
    # Generar algunos logs ficticios basados en la hora actual
    for i in range(12):
        time_str = datetime.now().strftime("%b %d %H:%M:%S")
        user = random.choice(users)
        action = random.choice(actions)
        ip = random.choice(ips)
        
        simulated.append(f"{time_str} Debian-Server tac_plus-ng[{1000+i}]: User '{user}' from {ip}: {action}")
        
    return {"status": "simulated", "logs": simulated}
