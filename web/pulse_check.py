import os
import requests
from sqlalchemy import create_engine, text

print("--- INITIATING CALDERA AI DATABASE PULSE CHECK ---")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://demo:demo_password@db:5432/demo_db")
engine = create_engine(DATABASE_URL)

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "CalderaAI:latest")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")


def get_ollama_urls():
    urls = []
    if OLLAMA_HOST:
        urls.append(f"http://{OLLAMA_HOST}:11434/api/generate")
    if os.getenv("OLLAMA_URL"):
        urls.append(os.getenv("OLLAMA_URL"))

    urls.extend([
        "http://127.0.0.1:11434/api/generate",
        "http://host.docker.internal:11434/api/generate",
        "http://172.17.0.1:11434/api/generate",
        "http://172.18.0.1:11434/api/generate",
    ])

    seen = set()
    deduped = []
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            deduped.append(url)
    return deduped


def build_data_summary(engine_instance):
    with engine_instance.connect() as conn:
        hours_result = conn.execute(text("SELECT SUM(hours) FROM shift_logs;")).fetchone()
        total_hours = hours_result[0] if hours_result[0] is not None else 0

        recent_shifts = conn.execute(text(
            "SELECT task, engine_check FROM shift_logs ORDER BY created_at DESC LIMIT 3;"
        )).fetchall()

        recent_strategies = conn.execute(text(
            "SELECT content FROM strategy_logs ORDER BY created_at DESC LIMIT 3;"
        )).fetchall()

    data_summary = f"Total Hours Logged on Ledger: {total_hours} Hours.\n"
    data_summary += "Recent Tasks Logged by Crew:\n"
    for s in recent_shifts:
        data_summary += f"- Task: {s[0]} | Check-in: \"{s[1]}\"\n"
    data_summary += "Recent Strategy Logs (AARs):\n"
    for st in recent_strategies:
        data_summary += f"- AAR: \"{st[0]}\"\n"
    return data_summary


def generate_talking_points(db_url=None, model=None, audit_context=None):
    engine_instance = create_engine(db_url or DATABASE_URL)
    model_name = model or OLLAMA_MODEL
    print("Extracting current ledger telemetry...")

    try:
        data_summary = build_data_summary(engine_instance)
        print("Telemetry extracted. Sending to CalderaAI Analyst...")

        prompt = f"""
        The database currently shows the following trends:
        {data_summary}

        Generate my talking points based on these specific entries.
        """
        if audit_context:
            prompt += f"\n\nRecent audit trail context:\n{audit_context}\n"

        urls = get_ollama_urls()
        print("Configured Ollama URLs:", urls)

        last_error = None
        for ollama_url in urls:
            print(f"Trying Ollama endpoint: {ollama_url}")
            try:
                response = requests.post(
                    ollama_url,
                    json={"model": model_name, "prompt": prompt, "stream": False},
                    timeout=60,
                )
                print(f"Received status {response.status_code} from {ollama_url}")
                if response.status_code == 200:
                    return response.json().get("response", "").strip()
                last_error = f"{ollama_url} returned {response.status_code}: {response.text}"
            except requests.exceptions.RequestException as exc:
                last_error = f"{ollama_url} failed: {exc}"

        print("\n[ERROR] Unable to reach Ollama with the configured endpoints.")
        print(f"Last failure: {last_error}")
        print("If you are running this from Docker, make sure the host allows TCP 11434 and that the model exists:")
        print("  ollama list")
        print("  sudo ufw allow 11434/tcp")
        return None
    except Exception as exc:
        print(f"\n[ERROR] The script encountered a roadblock: {exc}")
        return None
    finally:
        engine_instance.dispose()


def main():
    content = generate_talking_points()
    if content:
        print("\n================ FINAL STRATEGY ================\n")
        print(content)
        print("\n================================================\n")


if __name__ == "__main__":
    main()