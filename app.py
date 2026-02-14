import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import time
import re

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v25 Blindada", page_icon="🚀", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: GOOGLE_API_KEY no configurada.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y GESTIÓN DE HOJAS (FIXED)
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except Exception as e:
        st.error(f"Error de conexión con Google: {e}")
        return None

def obtener_o_crear_pestana(sh, nombre_usuario):
    nombre_hoja = f"Gasto-{nombre_usuario}"
    columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
    try:
        ws = sh.worksheet(nombre_hoja)
        # Verificamos si la primera fila tiene datos, si no, los ponemos
        if not ws.row_values(1):
            ws.insert_row(columnas, 1)
        return ws
    except gspread.exceptions.WorksheetNotFound:
        # Creamos la pestaña desde cero
        ws = sh.add_worksheet(title=nombre_hoja, rows="2000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

def safe_get_records(ws):
    """Lee registros de forma segura. Si falla, devuelve una lista vacía en lugar de romper la app."""
    try:
        data = ws.get_all_records()
        return data if data else []
    except Exception:
        return []

# ==========================================
# 🧠 3. MOTOR DE MONEDA (PARAGUAY PRO)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    if valor is None or valor == "": return 0
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    try:
        if es_cantidad:
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            s_limpio = re.sub(r'[^\d]', '', s) 
            return int(s_limpio) if s_limpio else 0
    except: return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Devuelve JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total)."},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload, timeout=40)
        texto_ia = response.json()['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

# --- LOGIN (Simulado para brevedad, usa tu lógica previa) ---
if not st.session_state.auth:
    st.title("🔐 Acceso Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        # Aquí iría tu check_login(u, p)
        st.session_state.auth, st.session_state.user, st.session_state.rol = True, u, 'admin'
        st.rerun()
else:
    menu = st.sidebar.radio("Navegación", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title("📥 Carga por Lote")
        files = st.file_uploader("Sube tus facturas", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button("Procesar"):
            items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': limpiar_monto_py(it.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(it.get('unitario')),
                            'Total': limpiar_monto_py(it.get('total'))
                        })
                bar.progress((idx + 1) / len(files))
            st.session_state.batch = pd.DataFrame(items)

# --- BLOQUE CORREGIDO ---
        if 'batch' in st.session_state and not st.session_state.batch.empty:
            st.markdown("---")
            st.subheader("📝 Revisión Previa al Guardado")
            
            # El editor debe estar indentado (un nivel adentro del IF)
            edited = st.data_editor(st.session_state.batch, use_container_width=True)
            
            if st.button("Confirmar y Guardar Todo", type="primary"):
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                existentes = pd.DataFrame(safe_get_records(ws))
                
                with st.spinner("Guardando en la nube..."):
                    for _, row in edited.iterrows():
                        # Generamos el ID único para evitar duplicados en Paraguay
                        id_u = f"{row['Proveedor']}_{row['Fecha']}_{row['Factura']}_{row['Producto']}".upper().replace(" ", "")
                        
                        if not existentes.empty and 'ID_Unico' in existentes.columns:
                            if id_u in existentes['ID_Unico'].values:
                                continue # Si ya existe, salta al siguiente sin error
                        
                        # Guardamos la fila con los montos ya limpios de la versión anterior
                        ws.append_row([
                            str(row['Fecha']), str(row['Proveedor']), str(row['Factura']), 
                            row['Producto'], row['Cantidad'], "u", 
                            row['Unitario'], row['Total'], st.session_state.user, 
                            id_u, str(datetime.datetime.now())
                        ])
                
                st.success(f"✅ ¡{len(edited)} registros procesados correctamente!")
                st.session_state.batch = None # Limpiamos la memoria para la próxima carga
                st.balloons()
