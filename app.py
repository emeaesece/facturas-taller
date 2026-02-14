import streamlit as st
import pandas as pd
import requests
import json
import base64
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import plotly.express as px
import re

# ==========================================
# ⚙️ 1. CONFIGURACIÓN
# ==========================================
st.set_page_config(page_title="Taller Pro - v27 Blindaje", page_icon="🔧", layout="wide")

if 'batch' not in st.session_state:
    st.session_state.batch = pd.DataFrame()

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: GOOGLE_API_KEY no configurada.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y GESTIÓN DE HOJAS
# ==========================================
def conectar_sheets():
    try:
        scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
        creds_dict = dict(st.secrets["gcp_service_account"])
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
        creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
        gc = gspread.authorize(creds)
        return gc.open("BaseDatos_Taller")
    except: return None

def obtener_o_crear_pestana(sh, nombre_usuario):
    nombre_hoja = f"Gasto-{nombre_usuario}"
    columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
    try:
        ws = sh.worksheet(nombre_hoja)
        # Verificamos encabezados por si la hoja está vacía
        headers = ws.row_values(1)
        if not headers or "ID_Unico" not in headers:
            ws.insert_row(columnas, 1)
        return ws
    except:
        ws = sh.add_worksheet(title=nombre_hoja, rows="3000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

# ==========================================
# 🧠 3. MOTOR DE PRECISIÓN (MONEDA Y CANTIDAD)
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    """
    Lógica 'As-Is' (Tal cual):
    - Moneda: Elimina todo lo que no sea número para evitar confusión con puntos/comas.
    - Cantidad: Mantiene el primer punto/coma como decimal.
    """
    if valor is None or str(valor).strip() == "": return 0
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    
    try:
        if es_cantidad:
            # Reemplaza coma por punto y deja solo un punto decimal
            s = s.replace(',', '.')
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # MONEDA PARAGUAYA: Quitamos CUALQUIER punto o coma. 
            # Si en la factura dice 10.500, el sistema debe guardar 10500.
            # Usamos Regex para dejar SOLAMENTE los números.
            s_solo_numeros = re.sub(r'\D', '', s)
            return int(s_solo_numeros) if s_solo_numeros else 0
    except:
        return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura de Paraguay. Extrae JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total). Copia los números exactamente como aparecen, sin redondear."},
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
# 🖥️ 4. INTERFAZ Y LÓGICA DE GUARDADO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Acceso Sistema Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Entrar"):
        st.session_state.auth, st.session_state.user = True, u
        st.rerun()
else:
    menu = st.sidebar.radio("Menú", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])
    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title(f"📥 Carga Masiva (Usuario: {st.session_state.user})")
        files = st.file_uploader("Sube tus facturas (Max 20)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} archivos"):
            all_items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                st.write(f"🔎 Analizando: {f.name}")
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        all_items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': limpiar_monto_py(it.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(it.get('unitario')),
                            'Total': limpiar_monto_py(it.get('total'))
                        })
                bar.progress((idx + 1) / len(files))
            st.session_state.batch = pd.DataFrame(all_items)

        if not st.session_state.batch.empty:
            st.markdown("---")
            st.subheader("📝 Verificación de Datos")
            edited = st.data_editor(st.session_state.batch, use_container_width=True)
            
            if st.button("Confirmar y Guardar en la Nube", type="primary"):
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                # OBTENEMOS TODOS LOS DATOS PARA COMPARAR DUPLICADOS
                data_actual = ws.get_all_records()
                df_actual = pd.DataFrame(data_actual)
                
                with st.spinner("Verificando duplicados y guardando..."):
                    for _, r in edited.iterrows():
                        # Generación de ID ÚNICO (Proveedor + Fecha + Factura + Producto)
                        id_u = f"{r['Proveedor']}_{r['Fecha']}_{r['Factura']}_{r['Producto']}".upper().replace(" ", "")
                        
                        # CHEQUEO REAL DE DUPLICADOS
                        if not df_actual.empty and 'ID_Unico' in df_actual.columns:
                            # Comparamos el ID generado con los IDs ya existentes en Sheets
                            if id_u in df_actual['ID_Unico'].astype(str).values:
                                st.warning(f"⚠️ El registro '{r['Producto']}' ya existe. Se omitió.")
                                continue
                        
                        ws.append_row([
                            str(r['Fecha']), str(r['Proveedor']), str(r['Factura']), 
                            str(r['Producto']), r['Cantidad'], "u", 
                            int(r['Unitario']), int(r['Total']), 
                            st.session_state.user, id_u, str(datetime.datetime.now())
                        ])
                
                st.success("✅ ¡Proceso terminado con éxito!")
                st.session_state.batch = pd.DataFrame()
                st.balloons()

    elif menu == "📅 Historial":
        st.title("📅 Historial")
        ws = obtener_o_crear_pestana(sh, st.session_state.user)
        df_hist = pd.DataFrame(ws.get_all_records())
        if not df_hist.empty:
            st.dataframe(df_hist.sort_values(by="Timestamp", ascending=False), use_container_width=True)
        else: st.info("No hay registros.")

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
