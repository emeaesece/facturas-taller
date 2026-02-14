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
st.set_page_config(page_title="Taller Pro - v32 Precisión", page_icon="🔧", layout="wide")

if 'batch' not in st.session_state:
    st.session_state.batch = pd.DataFrame()

try:
    API_KEY = st.secrets["GOOGLE_API_KEY"]
except:
    st.error("❌ Error: API Key no detectada.")
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
        headers = ws.row_values(1)
        if not headers or "ID_Unico" not in headers:
            ws.insert_row(columnas, 1)
        return ws
    except:
        ws = sh.add_worksheet(title=nombre_hoja, rows="3000", cols="20")
        ws.insert_row(columnas, 1)
        return ws

# ==========================================
# 🧠 3. MOTOR DE PRECISIÓN REFORZADO
# ==========================================
def limpiar_monto_py(valor, es_cantidad=False):
    """
    Lógica de alta precisión:
    - Cantidad: Protege el punto/comma decimal (ej: 0,295 -> 0.295).
    - Moneda: Elimina decimales (Paraguay) pero mantiene el valor entero.
    """
    if valor is None or str(valor).strip() == "": return 0.0
    
    # Si ya es un número, lo devolvemos según el tipo
    if isinstance(valor, (int, float)):
        return float(valor) if es_cantidad else int(valor)

    s = str(valor).upper().replace('GS', '').replace('$', '').replace(' ', '').strip()
    
    try:
        if es_cantidad:
            # Reemplazamos la coma decimal por punto para que Python lo entienda
            s = s.replace(',', '.')
            # Si hay más de un punto (separadores de miles), los quitamos excepto el último
            if s.count('.') > 1:
                partes = s.split('.')
                s = "".join(partes[:-1]) + "." + partes[-1]
            return float(s)
        else:
            # MONEDA: Eliminamos CUALQUIER punto o coma para evitar errores con 10.000
            # pero primero verificamos si la IA devolvió algo como '10000.0'
            if '.' in s: s = s.split('.')[0]
            if ',' in s: s = s.split(',')[0]
            s_solo_numeros = re.sub(r'\D', '', s)
            return int(s_solo_numeros) if s_solo_numeros else 0
    except:
        return 0.0

def analizar_factura_v1(archivo_bytes, mime_type):
    url = f"https://generativelanguage.googleapis.com/v1/models/gemini-2.0-flash:generateContent?key={API_KEY}"
    archivo_b64 = base64.b64encode(archivo_bytes).decode('utf-8')
    payload = {
        "contents": [{
            "parts": [
                {"text": "Analiza esta factura. Extrae JSON: fecha (YYYY-MM-DD), proveedor, nro_factura, e items (producto, cantidad, unitario, total)."},
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

if not st.session_state.auth:
    st.title("🔐 Sistema de Control - Taller")
    u = st.text_input("Usuario")
    p = st.text_input("Clave", type="password")
    if st.button("Ingresar"):
        st.session_state.auth, st.session_state.user = True, u
        st.rerun()
else:
    menu = st.sidebar.radio("Navegación", ["📥 Carga Masiva", "📊 Dashboard", "📅 Historial", "🚀 Salir"])
    sh = conectar_sheets()

    if menu == "📥 Carga Masiva":
        st.title(f"📥 Carga Masiva")
        files = st.file_uploader("Subir archivos", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True)
        
        if files and st.button(f"Procesar {len(files)} documentos"):
            all_items = []
            bar = st.progress(0)
            for idx, f in enumerate(files):
                d = analizar_factura_v1(f.getvalue(), f.type)
                if d:
                    for it in d.get('items', []):
                        c = limpiar_monto_py(it.get('cantidad'), True)
                        u_p = limpiar_monto_py(it.get('unitario'))
                        all_items.append({
                            'Fecha': d.get('fecha', ""), 'Proveedor': d.get('proveedor', ""),
                            'Factura': d.get('nro_factura', ""), 'Producto': it.get('producto', ""),
                            'Cantidad': c, 'Unitario': u_p, 'Total': int(round(c * u_p))
                        })
                bar.progress((idx + 1) / len(files))
            st.session_state.batch = pd.DataFrame(all_items)

        if not st.session_state.batch.empty:
            st.info("💡 Puedes usar decimales en Cantidad (ej: 0.295). El Total se recalculará automáticamente.")
            edited = st.data_editor(
                st.session_state.batch, 
                use_container_width=True,
                column_config={
                    "Cantidad": st.column_config.NumberColumn(format="%.3f"), # Soportamos 3 decimales
                    "Total": st.column_config.NumberColumn(disabled=True)
                }
            )
            
            if st.button("Guardar en la Nube", type="primary"):
                ws = obtener_o_crear_pestana(sh, st.session_state.user)
                df_act = pd.DataFrame(ws.get_all_records())
                with st.spinner("Sincronizando..."):
                    for _, r in edited.iterrows():
                        # Recálculo final de precisión
                        c_final = float(r['Cantidad'])
                        u_final = int(r['Unitario'])
                        t_final = int(round(c_final * u_final))
                        
                        id_u = f"{r['Proveedor']}_{r['Fecha']}_{r['Factura']}_{r['Producto']}".upper().replace(" ", "")
                        if not df_act.empty and id_u in df_act['ID_Unico'].astype(str).values: continue
                        
                        ws.append_row([
                            str(r['Fecha']), str(r['Proveedor']), str(r['Factura']), 
                            str(r['Producto']), c_final, "u", 
                            u_final, t_final, st.session_state.user, id_u, str(datetime.datetime.now())
                        ])
                st.success("✅ Datos guardados con precisión decimal.")
                st.session_state.batch = pd.DataFrame(); st.balloons()

    elif menu == "📅 Historial":
        st.title("📅 Gestión de Historial")
        ws = obtener_o_crear_pestana(sh, st.session_state.user)
        df_full = pd.DataFrame(ws.get_all_records())
        
        if not df_full.empty:
            df_display = df_full.copy()
            df_display.insert(0, "Eliminar", False)
            # Aseguramos que Cantidad sea float para el editor
            df_display['Cantidad'] = pd.to_numeric(df_display['Cantidad'], errors='coerce')
            
            # Buscador y Filtro
            busqueda = st.text_input("🔍 Buscar producto...")
            if busqueda:
                df_display = df_display[df_display['Producto'].astype(str).str.contains(busqueda, case=False)]

            df_edited = st.data_editor(
                df_display.sort_values(by="Timestamp", ascending=False),
                use_container_width=True,
                disabled=["ID_Unico", "Usuario", "Timestamp", "Total"],
                hide_index=True,
                column_config={"Cantidad": st.column_config.NumberColumn(format="%.3f")}
            )
            
            if st.button("💾 Aplicar Cambios", type="primary"):
                with st.spinner("Actualizando..."):
                    # Recalcular totales antes de guardar
                    df_edited['Total'] = (df_edited['Cantidad'] * df_edited['Unitario']).round().astype(int)
                    
                    ids_del = df_edited[df_edited['Eliminar'] == True]['ID_Unico'].values
                    df_full.set_index('ID_Unico', inplace=True)
                    df_upd = df_edited[df_edited['Eliminar'] == False].drop(columns=['Eliminar']).set_index('ID_Unico')
                    
                    df_full.update(df_upd)
                    df_full.reset_index(inplace=True)
                    df_final = df_full[~df_full['ID_Unico'].isin(ids_del)]
                    
                    ws.clear()
                    cols = ["Fecha", "Proveedor", "Factura", "Producto", "Cantidad", "Medida", "Unitario", "Total", "Usuario", "ID_Unico", "Timestamp"]
                    ws.update('A1', [cols] + df_final[cols].values.tolist())
                st.success("✅ Cambios sincronizados."); st.rerun()

    if menu == "🚀 Salir":
        st.session_state.auth = False; st.rerun()
