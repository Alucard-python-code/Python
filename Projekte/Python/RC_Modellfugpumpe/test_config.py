import importlib
import os
import tempfile
from pathlib import Path


def test_load_from_flash_uses_default_models_when_missing_fields(monkeypatch, tmp_path):
    module = importlib.import_module('config')
    module.sys_settings = module.SystemSettings()
    config_path = tmp_path / 'config.json'
    config_path.write_text('{"owner_name": "Alice", "models": [{"name": "Test", "size_l": 2.0, "tank_type": "Beutel", "max_press": 120, "defuel_time": 60}]}', encoding='utf-8')
    monkeypatch.chdir(tmp_path)

    module.sys_settings.load_from_flash()

    assert module.sys_settings.owner_name == 'Alice'
    assert len(module.sys_settings.models) == 10
    assert module.sys_settings.models[0].name == 'Test'
    assert module.sys_settings.models[0].tank_type == 'Beutel'
    assert module.sys_settings.models[1].name == 'Leer'


def test_hardware_modules_import_on_standard_python():
    importlib.invalidate_caches()
    hardware = importlib.import_module('hardware')
    rotary = importlib.import_module('rotary')

    assert hardware.pump is not None
    assert rotary.Rotary is not None
