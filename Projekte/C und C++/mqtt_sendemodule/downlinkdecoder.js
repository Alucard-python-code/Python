function Encoder(device, measurements) {
    
    // 1. Standard-Werte definieren (Falls nichts gefunden wird)
    var targetTopic = "dtck-cmd/v1/dein-produkt/" + device.serial_number + "/DIGITAL_OUT_1";
    var payloadValue = "0";
    
    // 2. Dynamisch nachschauen, welches Feld die Aktion ausgelöst hat
    // measurements enthält z.B. { DIGITAL_OUT_1: { value: true } }
    for (var fieldName in measurements) {
        if (measurements.hasOwnProperty(fieldName)) {
            
            // Topic passend für den Pico-Callback zusammensetzen
            targetTopic = "dtck-cmd/v1/dein-produkt/" + device.serial_number + "/" + fieldName;
            
            // True/False in "1"/"0" für das Relais übersetzen
            if (measurements[fieldName].value === true) {
                payloadValue = "1";
            } else {
                payloadValue = "0";
            }
            break; // Schleife abbrechen, da wir das geänderte Feld gefunden haben
        }
    }
    
    // 3. Datacake erwartet zwingend dieses Rückgabe-Objekt
    return {
        topic: targetTopic,
        payload: payloadValue
    };
}
