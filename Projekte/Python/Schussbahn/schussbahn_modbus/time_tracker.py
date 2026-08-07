# -*- coding: utf-8 -*-
from config_loader import save_operating_hours, save_settings

class TimeTracker:
    def __init__(self, parent_app):
        self.app = parent_app
        self.autosave_counter = 0

    def track_total_hours(self):
        """Wird im 1s-Takt aufgerufen, um die globale Systemzeit zu loggen."""
        self.app.hours_data["gesamt_sekunden"] += 1.0
        self.autosave_counter += 1
        if self.autosave_counter >= 60:
            save_operating_hours(self.app.hours_data)
            self.autosave_counter = 0

    def add_drive_time(self, seconds):
        """Addiert die tatsächliche Fahrzeit nach jedem beendeten Lauf."""
        self.app.hours_data["fahrzeit_sekunden"] += seconds
        save_operating_hours(self.app.hours_data) 
        
        neue_minuten = seconds / 60.0
        aktuelle_laufzeit = self.app.times.get("Laufzeit Motor (min)", 0.0)
        self.app.times["Laufzeit Motor (min)"] = aktuelle_laufzeit + neue_minuten
        save_settings(self.app.times)
