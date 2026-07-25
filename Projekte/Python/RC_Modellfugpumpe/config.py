import json

PSI_TO_MBAR = 68.9476

class ModelConfig:
    def __init__(self, name="Leer", size_l=1.0, tank_type="Fest", max_press=150, defuel_time=140):
        self.name = name
        self.size_l = size_l
        self.tank_type = tank_type      # "Fest" oder "Beutel"
        self.max_press = max_press      # in mbar
        self.defuel_time = defuel_time  # in Sekunden

    def to_dict(self):
        return self.__dict__

class SystemSettings:
    def __init__(self):
        self.owner_name = "Modell-Pilot"
        self.owner_address = "Flugplatzstr. 1"
        self.pin = "1234"
        self.puk = "87654321"
        self.pin_lock_enabled = False
        self.pulses_per_ml = 4.5
        self.pressure_offset = 0.0
        self.pin_attempts = 0
        self.system_locked = False
        self.models = [ModelConfig() for _ in range(10)]

    def save_to_flash(self):
        try:
            data = self.__dict__.copy()
            data['models'] = [m.to_dict() for m in self.models]
            with open("config.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            print("Fehler beim Speichern:", e)

    def load_from_flash(self):
        try:
            with open("config.json", "r") as f:
                data = json.load(f)
                self.owner_name = data.get("owner_name", self.owner_name)
                self.owner_address = data.get("owner_address", self.owner_address)
                self.pin = data.get("pin", self.pin)
                self.puk = data.get("puk", self.puk)
                self.pin_lock_enabled = data.get("pin_lock_enabled", self.pin_lock_enabled)
                self.pulses_per_ml = data.get("pulses_per_ml", self.pulses_per_ml)
                self.pressure_offset = data.get("pressure_offset", self.pressure_offset)
                
                raw_models = data.get("models", [])
                self.models = []
                for m in raw_models:
                    self.models.append(ModelConfig(m['name'], m['size_l'], m['tank_type'], m['max_press'], m['defuel_time']))
                # Auffüllen falls unvollständig
                while len(self.models) < 10:
                    self.models.append(ModelConfig())
        except OSError:
            print("Keine Konfiguration gefunden. Erstelle Standardwerte...")
            self.save_to_flash()

# Globales Einstellungs-Objekt bereitstellen
sys_settings = SystemSettings()
