function Encoder(device, measurements) {
    
    // 1. Fallback-Werte (Falls kein Feld zugeordnet werden kann)
    var targetTopic = "dtck-cmd/v1/dein-produkt/" + device.serial_number + "/DIGITAL_OUT_1";
    var payloadValue = "0";
    
    // 2. Das measurements-Objekt durchlaufen, um das geänderte Widget zu finden
    for (var fieldName in measurements) {
        if (measurements.hasOwnProperty(fieldName)) {
            
            // Baut exakt den Pfad, auf den der Pico in "mqttCallback" lauscht
            targetTopic = "dtck-cmd/v1/dein-produkt/" + device.serial_number + "_" + fieldName;
            
            // True/False Zustand des Dashboard-Switches in "1" oder "0" übersetzen
            if (measurements[fieldName].value === true) {
                payloadValue = "1";
            } else {
                payloadValue = "0";
            }
            break; // Schleife nach dem Treffer sofort beenden
        }
    }
    
    // 3. Rückgabe an den Datacake-MQTT-Broker
    return {
        topic: targetTopic,
        payload: payloadValue
    };
}
