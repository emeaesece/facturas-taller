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
st.set_page_config(page_title="Taller Pro - Gestión de Activos", page_icon="🚀", layout="wide")

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: GOOGLE_API_KEY no configurada.")
    st.stop()

# ==========================================
# ☁️ 2. CONEXIÓN Y UTILIDADES
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
    try:
        return sh.worksheet(nombre_hoja)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=nombre_hoja, rows="2000", cols="20")
        columnas = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
        ws.insert_row(columnas, 1)
        return ws

def check_login(u, p):
    try:
        sh = conectar_sheets()
        ws = sh.worksheet("Usuarios")
        for row in ws.get_all_records():
            if str(row['username']).lower() == str(u).lower() and str(row['password']) == str(p):
                return row.get('rol', 'usuario')
        return None
    except: return None

# ==========================================
# 🧠 3. MOTOR DE MONEDA (EL "PARAGUAYIZADOR")
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    """
    Lógica blindada para Paraguay 2026:
    - Cantidad: Mantiene decimales (2.5 litros).
    - Moneda: Elimina puntos y comas SIEMPRE. 10.000 es 10000.
    """
    if valor is None or valor == "": return 0
    
    # Convertir a string y quitar símbolos de moneda
    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    
    try:
        if es_cantidad:
            # Reemplazamos coma por punto para que Python entienda el decimal
            s = s.replace(',', '.')
            # Si el AI puso puntos de miles en la cantidad (ej: 1.000,50), los limpiamos
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # MONEDA (Guaraníes): En Paraguay NO usamos decimales. 
            # Cualquier punto o coma es un separador de miles que debemos ELIMINAR.
            # 10.000 -> 10000 | 10.500 -> 10500
            
            # Limpieza: Solo dejamos los dígitos
            s_limpio = re.sub(r'[^\d]', '', s) 
            return int(s_limpio) if s_limpio else 0
    except:
        return 0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": """Analiza esta factura paraguaya. Extrae JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total). 
                REGLA DE ORO: Los precios en Guaraníes son números enteros grandes. Si ves 10.000, extrae 10000. NUNCA uses decimales en los precios."""},
                {"inline_data": {"mime_type": mime_type, "data": archivo_b64}}
            ]
        }]
    }
    try:
        response = requests.post(url, json=payload, timeout=40)
        res_json = response.json()
        texto_ia = res_json['candidates'][0]['content']['parts'][0]['text']
        return json.loads(texto_ia.replace("```json", "").replace("```", "").strip())
    except: return None

# ==========================================
# 🖥️ 4. INTERFAZ DE USUARIO
# ==========================================
if 'auth' not in st.session_state: st.session_state.auth = False

if not st.session_state.auth:
    st.title("🔐 Control de Gastos Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Contraseña", type="password")
    if st.button("Acceder"):
        rol = check_login(u, p)
        if rol:
            st.session_state.auth, st.session_state.user, st.session_state.rol = True, u, rol
            st.rerun()
        else: st.error("Usuario o clave incorrectos.")
else:
    menu = st.sidebar.radio("Navegación", ["📥 Carga por Lote", "📊 Dashboard", "📅 Historial", "🚀 Salir"])

    if menu == "📥 Carga por Lote":
        st.title(f"📥 Carga Masiva para: {st.session_state.user}")
        files = st.file_uploader("Sube hasta 20 facturas", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"🚀 Procesar {len(files)} documentos"):
            all_items = []
            bar = st.progress(0)
            for i, f in enumerate(files):
                st.info(f"Leyendo: {f.name}...")
                datos = analizar_factura_v1(f.getvalue(), f.type)
                if datos:
                    for it in datos.get('items', []):
                        all_items.append({
                            'Fecha': datos.get('fecha', ""),
                            'Proveedor': datos.get('proveedor', ""),
                            'Factura': datos.get('nro_factura', ""),
                            'Producto': it.get('producto', ""),
                            'Cantidad': limpiar_monto_py(it.get('cantidad'), True),
                            'Unitario': limpiar_monto_py(it.get('unitario')),
                            'Total': limpiar_monto_py(it.get('total'))
                        })
                bar.progress((i + 1) / len(files))
            st.session_state.batch = pd.DataFrame(all_items)
            st.success("Análisis completo.")

        if 'batch' in st.session_state and not st.session_state.batch.empty:
            st.markdown("---")
            st.subheader("📝 Revisión Previa al Guardado")
            # El editor permite corregir si la IA leyó algo mal
            edited = st.data_editor(st.session_state.batch, use_container_width=True)
            
            if st.button("Confirmar y Guardar Todo", type="primary"):
                sh = conectar_sheets()
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                existentes = pd.DataFrame(ws.get_all_records())
                
                with st.spinner("Guardando..."):
                    for _, row in edited.iterrows():
                        id_u = f"{row['Proveedor']}_{row['Fecha']}_{row['Factura']}_{row['Producto']}".upper().replace(" ", "")
                        if not existentes.empty and 'ID_Unico' in existentes.columns:
                            if id_u in existentes['ID_Unico'].values: continue
                        
                        ws.append_row([
                            str(row['Fecha']), str(row['Proveedor']), str(row['Factura']), 
                            row['Producto'], row['Cantidad'], "u", 
                            row['Unitario'], row['Total'], st.session_state.user, 
                            id_u, str(datetime.datetime.now())
                        ])
                st.success("✅ Guardado exitoso.")
                st.session_state.batch = None
                st.balloons()

    elif menu == "📊 Dashboard":
        st.title("📊 Resumen Gerencial")
        sh = conectar_sheets()
        if st.session_state.rol == "admin":
            dfs = [pd.DataFrame(h.get_all_records()) for h in sh.worksheets() if h.title.startswith("Gasto-")]
            df = pd.concat(dfs) if dfs else pd.DataFrame()
        else:
            df = pd.DataFrame(obtener_o_crear_pestana(sh, st.session_state.user).get_all_records())

        if not df.empty:
            df['Total'] = pd.to_numeric(df['Total'], errors='coerce')
            st.metric("Inversión Total", f"{df['Total'].sum():,.0f} Gs.")
            st.plotly_chart(px.bar(df.groupby('Proveedor')['Total'].sum().reset_index(), x='Proveedor', y='Total'))
        else: st.info("Sin datos.")

    elif menu == "📅 Historial":
        st.title("📅 Mis Registros")
        sh = conectar_sheets()
        if st.session_state.rol == "admin":
            hojas = [h.title for h in sh.worksheets() if h.title.startswith("Gasto-")]
            sel = st.selectbox("Ver registros de:", hojas)
            df = pd.DataFrame(sh.worksheet(sel).get_all_records())
        else:
            df = pd.DataFrame(obtener_o_crear_pestana(sh, st.session_state.user).get_all_records())
            
        if not df.empty:
            df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
            mes = st.selectbox("Filtrar por Mes", ["Todos"] + list(df['Fecha'].dt.strftime('%Y-%m').unique()))
            if mes != "Todos": df = df[df['Fecha'].dt.strftime('%Y-%m') == mes]
            st.dataframe(df.sort_values('Fecha', ascending=False), use_container_width=True)

    if menu == "🚀 Salir":
        st.session_state.auth = False
        st.rerun()
