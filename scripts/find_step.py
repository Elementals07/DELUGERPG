import json

path = r"C:\Users\dugge\.gemini\antigravity\brain\496981d2-fa5b-41b6-9576-df7287935de1\.system_generated\logs\transcript_full.jsonl"
with open(path, "r", encoding="utf-8") as f:
    for line in f:
        data = json.loads(line)
        if data.get("step_index") == 292:
            tc = data["tool_calls"][0]
            content = tc["args"]["Content"]
            lines = content.split("\n")
            for idx, l in enumerate(lines):
                if "Extract current player" in l or "cx" in l:
                    for sub in lines[max(0, idx-5):min(len(lines), idx+15)]:
                        print(sub)
                    break
