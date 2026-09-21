function Decoder(request) {
    var body = JSON.parse(request.body);
    var jsonArray = Array.isArray(body) ? body : [body];
    var hexPayload = "";
    
    for (var i = 0; i < jsonArray.length; i++) {
        if (jsonArray[i].field === "PAYLOAD" || jsonArray[i].field === "payload") {
            hexPayload = jsonArray[i].value;
            break;
        }
    }
    if (!hexPayload || hexPayload.length < 4) return [];
    
    var bytes = [];
    for (var j = 0; j < hexPayload.length; j += 2) {
        bytes.push(parseInt(hexPayload.substr(j, 2), 16));
    }
    
    function bytesToFloat(b, offset) {
        var bits = (b[offset] << 24) | (b[offset + 1] << 16) | (b[offset + 2] << 8) | b[offset + 3];
        var sign = (bits >>> 31) === 0 ? 1 : -1;
        var exponent = (bits >>> 23) & 0xff;
        var fraction = (exponent === 0) ? (bits & 0x7fffff) << 1 : (bits & 0x7fffff) | 0x800000;
        return sign * fraction * Math.pow(2, exponent - 150);
    }
    
    var datacakeFields = [];
    var index = 0;
    var totalAnalogChannels = 0;
    
    while (index < bytes.length) {
        var header = bytes[index++];
        
        if (header === 0xAA) { // ANALOG-BLOCK PARSEN
            var numChannels = bytes[index++];
            totalAnalogChannels = numChannels;
            for (var a = 1; a <= numChannels; a++) {
                var maVal = bytesToFloat(bytes, index); index += 4;
                datacakeFields.push({ field: "ANALOG_IN_" + a, value: Math.round(maVal * 10000) / 10000 });
            }
        } 
        else if (header === 0x11) { // DIGITAL-IN BLOCK
            var numDiBytes = bytes[index++];
            var diCount = 1;
            for (var bIn = 0; bIn < numDiBytes; bIn++) {
                var diByte = bytes[index++];
                for (var bitI = 0; bitI < 8; bitI++) {
                    datacakeFields.push({ field: "DIGITAL_IN_" + diCount++, value: (diByte & (1 << bitI)) !== 0 });
                }
            }
        } 
        else if (header === 0x22) { // DIGITAL-OUT IST-MELDUNG
            var numDoBytes = bytes[index++];
            var doCount = 1;
            for (var bOut = 0; bOut < numDoBytes; bOut++) {
                var doByte = bytes[index++];
                for (var bitO = 0; bitO < 8; bitO++) {
                    datacakeFields.push({ field: "DIGITAL_OUT_" + doCount++, value: (doByte & (1 << bitO)) !== 0 });
                }
            }
        } 
        else if (header === 0x99) { // SYSTEM-STATUS & DIAGNOSE-FLAGS
            datacakeFields.push({ field: "SAMPLING_MODE", value: (bytes[index++] === 1) ? "EVENT_1_SEK" : "STANDARD_5_MIN" });
            
            var fault1 = bytes[index++];
            var fault2 = bytes[index++];
            var combinedFaults = (fault2 << 8) | fault1;
            
            // Gibt den Zustand jedes Kanals einzeln an das Dashboard weiter
            for (var c = 1; c <= totalAnalogChannels; c++) {
                datacakeFields.push({ field: "SENSOR_" + c + "_OK", value: (combinedFaults & (1 << (c - 1))) === 0 });
            }

            // Versorgungsspannung zurückrechnen (skaliertes Byte)
            var vInByte = bytes[index++];
            datacakeFields.push({ field: "SUPPLY_VOLTAGE", value: vInByte / 10.0 });
        } else {
            break;
        }
    }
    return datacakeFields;
}
