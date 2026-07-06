import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from novax import Novax

from app.cube_transfer_loop import start_cube_transfer, start_cube_transfer_steps_1_3
from app.pick_and_place import start

BASE_PATH = os.getenv("BASE_PATH", "")

app = FastAPI(
    title="Nova Pick and Place Demo",
    root_path=BASE_PATH,
)

# Enable CORS for frontend clients
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Set up Novax and register our pick_and_place program
novax = Novax()
novax.include_programs_router(app)
novax.register_program(start)
novax.register_program(start_cube_transfer)
novax.register_program(start_cube_transfer_steps_1_3)

@app.get("/health", summary="Health check endpoint")
def health():
    return {"status": "ok"}

@app.get("/status", summary="Get status of running program")
def status():
    return {
        "is_running": novax.program_manager.is_any_program_running,
        "running_program": novax.program_manager.running_program,
    }

@app.get("/", summary="Opens the interactive control dashboard", response_class=HTMLResponse)
async def root():
    return f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1, shrink-to-fit=no">
        <title>Nova Pick and Place Control Dashboard</title>
        <style>
          :root {{
            --primary: #5850ec;
            --primary-hover: #453ec9;
            --bg-page: #f9fafb;
            --bg-card: #ffffff;
            --text-dark: #111827;
            --text-muted: #6b7280;
            --success: #10b981;
            --danger: #ef4444;
            --border: #e5e7eb;
          }}
          body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-page);
            color: var(--text-dark);
            margin: 0;
            padding: 0;
          }}
          .header {{
            background-color: #1f2937;
            color: white;
            padding: 1.5rem;
            text-align: center;
            border-bottom: 4px solid var(--primary);
            box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1);
          }}
          .header h1 {{
            margin: 0;
            font-size: 1.8rem;
            font-weight: 700;
          }}
          .header p {{
            margin: 0.5rem 0 0 0;
            color: #9ca3af;
            font-size: 0.95rem;
          }}
          .container {{
            max-width: 800px;
            margin: 2rem auto;
            padding: 0 1.5rem;
          }}
          .card {{
            background: var(--bg-card);
            border-radius: 12px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05), 0 4px 6px -2px rgba(0, 0, 0, 0.02);
            border: 1px solid var(--border);
            padding: 2rem;
            margin-bottom: 2rem;
          }}
          .card-title {{
            margin-top: 0;
            margin-bottom: 1.5rem;
            font-size: 1.3rem;
            font-weight: 600;
            border-bottom: 2px solid var(--border);
            padding-bottom: 0.5rem;
          }}
          .status-badge {{
            display: inline-flex;
            align-items: center;
            padding: 0.35rem 1rem;
            border-radius: 9999px;
            font-weight: 600;
            font-size: 0.9rem;
          }}
          .status-idle {{
            background-color: #ecfdf5;
            color: var(--success);
          }}
          .status-running {{
            background-color: #ebf5ff;
            color: var(--primary);
            animation: pulse-bg 2s infinite;
          }}
          .status-dot {{
            width: 8px;
            height: 8px;
            border-radius: 50%;
            margin-right: 6px;
          }}
          .bg-success {{ background-color: var(--success); }}
          .bg-primary {{ background-color: var(--primary); }}
          .bg-danger {{ background-color: var(--danger); }}
          
          .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
          }}
          @media (max-width: 600px) {{
            .grid {{
              grid-template-columns: 1fr;
            }}
          }}
          
          .form-group {{
            margin-bottom: 1.25rem;
          }}
          label {{
            display: block;
            margin-bottom: 0.5rem;
            font-weight: 500;
            font-size: 0.95rem;
          }}
          input, select {{
            width: 100%;
            padding: 0.75rem;
            border-radius: 6px;
            border: 1px solid var(--border);
            font-size: 0.95rem;
            box-sizing: border-box;
          }}
          input:focus, select:focus {{
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(88, 80, 236, 0.15);
          }}
          
          .btn {{
            display: inline-block;
            width: 100%;
            padding: 0.85rem 1.5rem;
            border-radius: 6px;
            font-size: 1rem;
            font-weight: 600;
            text-align: center;
            border: none;
            cursor: pointer;
            transition: all 0.2s ease;
          }}
          .btn-success {{
            background-color: var(--success);
            color: white;
          }}
          .btn-success:hover:not(:disabled) {{
            background-color: #059669;
          }}
          .btn-danger {{
            background-color: var(--danger);
            color: white;
          }}
          .btn-danger:hover:not(:disabled) {{
            background-color: #dc2626;
          }}
          .btn:disabled {{
            opacity: 0.5;
            cursor: not-allowed;
          }}
          
          .workflow-steps {{
            list-style: none;
            padding: 0;
            margin: 0;
          }}
          .workflow-steps li {{
            position: relative;
            padding-left: 2rem;
            margin-bottom: 1rem;
            font-size: 0.95rem;
            line-height: 1.4;
          }}
          .workflow-steps li::before {{
            content: "➔";
            position: absolute;
            left: 0;
            color: var(--primary);
            font-weight: bold;
          }}
          
          .footer {{
            text-align: center;
            margin-top: 3rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
            color: var(--text-muted);
            font-size: 0.85rem;
          }}
          .footer a {{
            color: var(--primary);
            text-decoration: none;
            margin: 0 0.5rem;
          }}
          .footer a:hover {{
            text-decoration: underline;
          }}
          
          @keyframes pulse-bg {{
            0%, 100% {{ opacity: 1; }}
            50% {{ opacity: 0.7; }}
          }}
          .pulse {{
            animation: pulse-bg 1.5s infinite;
          }}
        </style>
      </head>
      <body>
        <div class="header">
          <h1>Wandelbots NOVA Dashboard</h1>
          <p>Local Cell & Robot Controller</p>
        </div>
        
        <div class="container">
          <div class="card">
            <h2 class="card-title">Program Status</h2>
            <div style="display: flex; justify-content: space-between; align-items: center;">
              <div>
                <span id="status-badge" class="status-badge status-idle">
                  <span id="status-dot" class="status-dot bg-success"></span>
                  <span id="status-text">Idle</span>
                </span>
                <span id="running-info" style="margin-left: 1rem; font-weight: 500; display: none;"></span>
              </div>
              <div id="loader" class="pulse" style="font-size: 1.5rem; display: none;">🤖 Working...</div>
            </div>
          </div>
          
          <div class="grid">
            <div class="card">
              <h2 class="card-title">Control Panel</h2>
              <form id="control-form" onsubmit="event.preventDefault(); startProgram();">
                <div class="form-group">
                  <label for="count">Cycle Repeat Count (1 to 10):</label>
                  <input type="number" id="count" name="count" min="1" max="10" value="4">
                </div>
                <div class="form-group">
                  <label for="controller_name">Robot Controller Name:</label>
                  <input type="text" id="controller_name" name="controller_name" value="ur10e">
                </div>
                <div style="margin-top: 1.5rem;">
                  <button type="submit" id="btn-start" class="btn btn-success">Start Program</button>
                  <button type="button" id="btn-stop" class="btn btn-danger" style="margin-top: 0.75rem;" onclick="stopProgram()" disabled>Stop Program</button>
                </div>
              </form>
            </div>
            
            <div class="card">
              <h2 class="card-title">Demo Motion Workflow</h2>
              <p style="color: var(--text-muted); font-size: 0.95rem; margin-top: 0;">This application performs a repeating pick-and-place operation:</p>
              <ul class="workflow-steps">
                <li><strong>Home Position:</strong> Transitions collision-free from joint configuration space.</li>
                <li><strong>Pick from Target:</strong> Moves cartesian path to pick at fixed coordinate (491.9, -133.3, -71.4).</li>
                <li><strong>Place on Table:</strong> Safely places workpiece onto randomly generated coordinates inside workspace.</li>
                <li><strong>Retrieve and Reset:</strong> Retrieves workpiece back from random coordinate and places it back at original target.</li>
              </ul>
            </div>
          </div>
          
          <div class="footer">
            <p>Designed with ❤️ for Wandelbots NOVA physical cells. Works offline.</p>
            <p>
              <a href="{BASE_PATH}/docs" target="_blank">Swagger OpenAPI UI</a> | 
              <a href="{BASE_PATH}/redoc" target="_blank">ReDoc UI</a> | 
              <a href="{BASE_PATH}/openapi.json" target="_blank">OpenAPI JSON Schema</a>
            </p>
          </div>
        </div>
        
        <script>
          const BASE_PATH = "{BASE_PATH}";
          
          // Poll every 1.5 seconds to track state
          let isRunning = false;
          
          async function fetchStatus() {{
            try {{
              const res = await fetch(`${{BASE_PATH}}/status`);
              if (!res.ok) return;
              const data = await res.json();
              
              const badge = document.getElementById("status-badge");
              const dot = document.getElementById("status-dot");
              const text = document.getElementById("status-text");
              const runningInfo = document.getElementById("running-info");
              const ldr = document.getElementById("loader");
              
              const btnStart = document.getElementById("btn-start");
              const btnStop = document.getElementById("btn-stop");
              
              const countInput = document.getElementById("count");
              const controllerInput = document.getElementById("controller_name");
              
              isRunning = data.is_running;
              
              if (isRunning) {{
                badge.className = "status-badge status-running";
                dot.className = "status-dot bg-primary";
                text.textContent = "Running";
                runningInfo.textContent = `Executing "${{data.running_program}}"`;
                runningInfo.style.display = "inline";
                ldr.style.display = "block";
                
                btnStart.disabled = true;
                btnStop.disabled = false;
                countInput.disabled = true;
                controllerInput.disabled = true;
              }} else {{
                badge.className = "status-badge status-idle";
                dot.className = "status-dot bg-success";
                text.textContent = "Idle";
                runningInfo.style.display = "none";
                ldr.style.display = "none";
                
                btnStart.disabled = false;
                btnStop.disabled = true;
                countInput.disabled = false;
                controllerInput.disabled = false;
              }}
            }} catch (err) {{
              console.error("Failed to poll status:", err);
            }}
          }}
          
          async function startProgram() {{
            const count = parseInt(document.getElementById("count").value);
            const controller_name = document.getElementById("controller_name").value;
            
            try {{
              const res = await fetch(`${{BASE_PATH}}/programs/pick_and_place/start`, {{
                method: "POST",
                headers: {{ "Content-Type": "application/json" }},
                body: JSON.stringify({{
                  arguments: {{ count, controller_name }}
                }})
              }});
              if (!res.ok) {{
                const errData = await res.json();
                alert(`Error starting program: ${{JSON.stringify(errData)}}`);
                return;
              }}
              fetchStatus();
            }} catch (err) {{
              alert(`Network error starting program: ${{err.message}}`);
            }}
          }}
          
          async function stopProgram() {{
            try {{
              const res = await fetch(`${{BASE_PATH}}/programs/pick_and_place/stop`, {{
                method: "POST"
              }});
              if (!res.ok) {{
                alert("Error stopping program.");
              }}
              fetchStatus();
            }} catch (err) {{
              alert(`Network error stopping program: ${{err.message}}`);
            }}
          }}
          
          // Start Polling loop
          fetchStatus();
          setInterval(fetchStatus, 1500);
        </script>
      </body>
    </html>
    """

@app.get("/app_icon.png", include_in_schema=False)
def app_icon():
    return FileResponse("app/static/app_icon.png")