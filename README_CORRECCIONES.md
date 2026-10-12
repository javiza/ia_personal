# Correcciones de Jarvis (Linux Mint)

Este paquete contiene archivos completos para reemplazar en tu proyecto existente:

- `config.py`: permite configurar modelos Gemini desde el entorno y acorta los reintentos por límites de cuota.
- `llm.py`: descubre modelos Gemini disponibles con la API key configurada, evita repetir proveedores sin credenciales y descarta Gemini durante la solicitud actual si devuelve un modelo inexistente.
- `tools.py`: cuando se solicita una carpeta que no existe, sugiere carpetas reales cercanas en lugar de dejar el error sin contexto; refuerza las instrucciones de la herramienta para que el modelo use rutas comprobadas.
- `rutas.py`: incluido como referencia completa; no necesita cambios en esta revisión.

## Instalación segura

1. Cierra Jarvis.
2. Abre una terminal y entra en tu carpeta real del proyecto:

   ```bash
   cd ~/Desktop/proyectos/jarvis
   ```

   Si la tienes en otra ubicación, cambia esa ruta por la real.
3. Haz una copia de seguridad de los archivos antes de reemplazarlos:

   ```bash
   ```bash
   RESPALDO="$HOME/JarvisArchivos/respaldo-codigo-$(date +%Y%m%d-%H%M%S)"
   mkdir -p "$RESPALDO"
   cp config.py llm.py tools.py rutas.py "$RESPALDO"/
   ```
4. Extrae el ZIP de correcciones en una carpeta temporal. Copia los cuatro `.py` al directorio de Jarvis, aceptando reemplazarlos. No reemplaces `ajustes.json`, `memoria.sqlite3`, `.env` ni `~/.config/jarvis/env`.
5. Comprueba sintaxis antes de iniciar:

   ```bash
   python -m py_compile config.py llm.py rutas.py tools.py
   ```

6. Inicia Jarvis como lo haces normalmente, por ejemplo `./iniciar.sh`.

## Claves API

No escribas claves en `config.py` ni las compartas en capturas o logs. El programa sigue leyendo las claves desde el entorno, `jarvis/.env` o `~/.config/jarvis/env`. Para Gemini, usa una línea `GEMINI_API_KEY=...`; para Groq, `GROQ_API_KEY=...`; para Anthropic, `ANTHROPIC_API_KEY=...`. Protege el archivo de entorno con permisos restrictivos:

```bash
chmod 600 ~/.config/jarvis/env
```

Solo configura proveedores que realmente utilices. El orden híbrido permanece `groq, gemini, anthropic, ollama` salvo que `JARVIS_CEREBROS` lo sobrescriba. Los proveedores sin clave se omiten sin intentar llamadas.

## Modelos Gemini

Jarvis consulta el catálogo de modelos asociado a tu API key y prefiere los modelos Flash disponibles. Si no logra consultar el catálogo, utiliza la lista de respaldo configurable con `GEMINI_MODELOS` en el entorno. La disponibilidad y los límites siguen dependiendo de Google y de tu cuenta.

## Pruebas recomendadas

1. En el chat, pide `lista los archivos de Escritorio/proyectos`.
2. Pide `muestra el árbol de Escritorio/proyectos/jarvis con profundidad 2`.
3. Prueba una pregunta simple para comprobar la cadena de proveedores.
4. Si un proveedor falla, revisa el log: no compartas claves ni encabezados de autenticación.

## Alcance y limitaciones

Las rutas inexistentes ahora devuelven sugerencias concretas, pero Jarvis no adivina ni crea automáticamente una carpeta de proyecto cuando no existe. Debe usar una ruta que haya comprobado. Las correcciones no pueden eliminar límites de cuota de Groq, habilitar modelos que Google no ofrezca para tu cuenta ni acelerar el hardware local; mejoran la selección, el diagnóstico y el paso al siguiente proveedor.
