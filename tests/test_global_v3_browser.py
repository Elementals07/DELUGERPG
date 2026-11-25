import json
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
WEIGHTS = ROOT / "data" / "processed" / "global_49map_v3_browser_weights.json"
CHECKPOINT = ROOT / "models" / "global_49map_dqn_v3_best.pt"
USERSCRIPT = ROOT / "deluge_global_ai_v3.user.js"


def test_v3_browser_weights_export_exists_and_matches_metadata():
    assert WEIGHTS.is_file()
    payload = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    assert payload["model_version"] == "Global49MapDQN-v3"
    assert payload["checkpoint"] == "global_49map_dqn_v3_best.pt"
    assert payload["checkpoint_episode"] == 4400
    assert payload["input_dim"] == 190
    assert payload["output_dim"] == 11
    assert len(payload["map_names"]) == 49
    assert len(payload["walkgrids"]) == 49
    assert len(payload["macro_edges"]) > 100000
    assert len(payload["action_names"]) == 11
    assert payload["parameters"]["feature_net.0.weight"]
    assert len(payload["parameters"]["feature_net.0.weight"]) == 256


def test_v3_export_command_uses_real_checkpoint():
    result = subprocess.run(
        [
            "python",
            str(ROOT / "scripts" / "export_global_v3_browser_weights.py"),
            "--checkpoint",
            str(CHECKPOINT),
            "--output",
            str(WEIGHTS),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "pass=True" in result.stdout


def test_userscript_is_valid_javascript():
    result = subprocess.run(
        ["node", "--check", str(USERSCRIPT)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_userscript_exact_test_vector_forward_pass_matches_python():
    payload = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weightsPath = process.argv[2];
const scriptPath = process.argv[3];
const weights = JSON.parse(fs.readFileSync(weightsPath, 'utf8'));
const code = fs.readFileSync(scriptPath, 'utf8');
global.location = { pathname: '/map/overworld1' };
global.document = {};
global.window = {
  addEventListener: function () {},
  busy: 0
};
const context = { window, location, document, console,
  indexedDB: undefined, atob, performance,
  btoa, Float32Array, Array, Map, Set };
vm.createContext(context);
vm.runInContext(code, context);
context.window.__DELUGE_GLOBAL_AI_V3_TESTING__.setModel(weights);
context.window.__DELUGE_GLOBAL_AI_V3_TESTING__.setTarget('overworld1', 2);
const results = weights.test_vectors.map(test => {
  const q = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__.forwardPass(test.observation);
  let action = 0;
  for (let i = 1; i < q.length; i++) if (q[i] > q[action]) action = i;
  return {qvalues: q, action};
});
process.stdout.write(JSON.stringify(results));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    js_results = json.loads(result.stdout)
    for test, js_result in zip(payload["test_vectors"], js_results):
        max_error = max(
            abs(float(python_q) - float(js_q))
            for python_q, js_q in zip(test["python_qvalues"], js_result["qvalues"])
        )
        assert max_error <= 2e-5
        assert test["python_selected_action"] == js_result["action"]


def test_userscript_map_and_path_helpers_require_loaded_model():
    payload = json.loads(WEIGHTS.read_text(encoding="utf-8"))
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weights = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const code = fs.readFileSync(process.argv[3], 'utf8');
global.location = { pathname: '/map/overworld1' };
global.document = {};
global.window = { addEventListener: function () {}, busy: 0 };
const context = { window, location, document, console,
  indexedDB: undefined, atob, btoa, performance, Map, Set, Array };
vm.createContext(context);
vm.runInContext(code, context);
const api = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__;
api.setModel(weights);
api.setTarget('overworld1', 2);
const map = api.detectMap();
const obs = api.buildObservation(map, {x: 16, y: 16});
const path = api.findPath(map, 16, 16, 8, 8);
process.stdout.write(JSON.stringify({map, obsLength: obs.observation.length,
  maskLength: obs.mask.length, pathLength: path ? path.length : null}));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    result_payload = json.loads(result.stdout)
    assert result_payload["map"] == "overworld1"
    assert result_payload["obsLength"] == 190
    assert result_payload["maskLength"] == 11


def test_visible_pokemon_does_not_trigger_safety_stop():
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weights = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const code = fs.readFileSync(process.argv[3], 'utf8');
const sprite = {parentElement: {style: {top: '223px', left: '233px'}}};
global.location = {pathname: '/map/overworld1'};
global.document = {
  title: 'DelugeRPG',
  body: {innerText: ''},
  getElementById: id => id === 'usersprite' ? sprite : null,
  querySelector: selector => selector.includes('#encounter') ? {offsetParent: {}} : null
};
global.window = {addEventListener: function () {}, busy: 1};
const context = {window, location, document, console, atob, btoa,
  performance, Map, Set, Array, Float32Array, indexedDB: undefined};
vm.createContext(context);
vm.runInContext(code, context);
const api = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__;
api.setModel(weights);
process.stdout.write(JSON.stringify({
  encounterVisible: api.isEncounterVisible(),
  safetyStop: api.safetyCheck()
}));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"encounterVisible": True, "safetyStop": None}


def test_game_movement_busy_flag_is_waitable_not_a_safety_stop():
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weights = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const code = fs.readFileSync(process.argv[3], 'utf8');
const sprite = {parentElement: {style: {top: '223px', left: '233px'}}};
global.location = {pathname: '/map/overworld1'};
global.document = {
  title: 'DelugeRPG',
  body: {innerText: ''},
  getElementById: id => id === 'usersprite' ? sprite : null,
  querySelector: () => null
};
global.window = {addEventListener: function () {}, busy: 1};
const context = {window, location, document, console, atob, btoa,
  performance, Map, Set, Array, Float32Array, indexedDB: undefined};
vm.createContext(context);
vm.runInContext(code, context);
const api = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__;
api.setModel(weights);
process.stdout.write(JSON.stringify({
  busy: api.isGameBusy(),
  safetyStop: api.safetyCheck()
}));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {"busy": True, "safetyStop": None}


def test_browser_action_mask_matches_trainer_for_global_route():
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weights = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const code = fs.readFileSync(process.argv[3], 'utf8');
global.location = {pathname: '/map/overworld1'};
global.document = {};
global.window = {addEventListener: function () {}, busy: 0};
const context = {window, location, document, console, atob, btoa,
  performance, Map, Set, Array, Float32Array, indexedDB: undefined};
vm.createContext(context);
vm.runInContext(code, context);
const api = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__;
api.setModel(weights);
api.setTarget('overworld6', 2);
const mask = api.buildActionMask('overworld1', {x: 16, y: 16});
const executable = api.buildExecutionMask('overworld1', {x: 16, y: 16}, mask);
process.stdout.write(JSON.stringify({mask, executable}));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout)
    assert actual["mask"] == [
        False, False, False, False, False, False, True, False, True, True, False
    ]
    assert actual["executable"] == [False] * 11


def test_same_map_target_has_at_least_one_trained_legal_local_action():
    js = r"""
const fs = require('fs');
const vm = require('vm');
const weights = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const code = fs.readFileSync(process.argv[3], 'utf8');
global.location = {pathname: '/map/overworld1'};
global.document = {};
global.window = {addEventListener: function () {}, busy: 0};
const context = {window, location, document, console, atob, btoa,
  performance, Map, Set, Array, Float32Array, indexedDB: undefined};
vm.createContext(context);
vm.runInContext(code, context);
const api = context.window.__DELUGE_GLOBAL_AI_V3_TESTING__;
api.setModel(weights);
api.setTarget('overworld1', 0);
const modelMask = api.buildActionMask('overworld1', {x: 16, y: 16});
const executionMask = api.buildExecutionMask('overworld1', {x: 16, y: 16}, modelMask);
process.stdout.write(JSON.stringify({modelMask, executionMask}));
"""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
        handle.write(js)
        js_path = handle.name
    try:
        result = subprocess.run(
            ["node", js_path, str(WEIGHTS), str(USERSCRIPT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    finally:
        Path(js_path).unlink(missing_ok=True)
    assert result.returncode == 0, result.stderr
    result_payload = json.loads(result.stdout)
    assert len(result_payload["modelMask"]) == 11
    assert result_payload["modelMask"][0] is True
    assert result_payload["executionMask"][0] is True
    assert not any(result_payload["executionMask"][5:])
