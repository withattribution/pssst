import network, time, machine, ubinascii, logging
import onewire, ds18x20
from umqtt.simple import MQTTClient

WAKE_AFTER_TIME = 60000   #sleep time in ms
FEED_TIME = 10000         #pssst time in ms
AP_TIME_OUT = 30000       #wait for max time (ms) for network, if no net then proceed
RETRY_DELAY = 3000        #MQTT connect delay (ms)

#static ip because dns ruined my life
MQTT_SERVER = '192.168.0.100'
MQTT_PORT = 4444

AP_LOGIN = ''
AP_PASS = ''

VERSION = 'ALPHA'
DEVICE_ID = ubinascii.hexlify(machine.unique_id()).decode()

TOPIC_TEMP = VERSION+'/'+DEVICE_ID+'/TEMP'
TOPIC_COUNT = VERSION+'/'+DEVICE_ID+'/COUNT'

TEMPERATURE_PIN = 12
PSSST_PIN = 14
LED_PIN = 2

DEBUG = False

### Configuration

def check_reset():
    if machine.reset_cause() == machine.DEEPSLEEP_RESET:
        log.debug("(%s)", "woke from deep sleep")
        return 2
    else:
        log.debug("(%s)", "woke from hard reset")
        return 4

def configure_pins():
    temp = machine.Pin(TEMPERATURE_PIN)
    pssst = machine.Pin(PSSST_PIN,machine.Pin.OUT,value=0)
    led = machine.Pin(LED_PIN,machine.Pin.OUT)
    return {'temp':temp,'pssst':pssst,'led':led}

def config_deep_sleep():
    # configure RTC.ALARM0 to be able to wake the device
    rtc = machine.RTC()
    rtc.irq(trigger=rtc.ALARM0, wake=machine.DEEPSLEEP)
    # set RTC.ALARM0 to fire after WAKE_AFTER_TIME seconds (waking the device)
    rtc.alarm(rtc.ALARM0, WAKE_AFTER_TIME)

def flash_led(p,n,t=300):
    for i in range(2*n):
        p.value(not p.value())
        time.sleep_ms(t)
    #make sure led off
    p.value(1)

### Establish Connections

def connect_mqtt_broker(n):
    try:
        client = MQTTClient(VERSION+"_"+DEVICE_ID, MQTT_SERVER, MQTT_PORT)
    except OSError as e:
        log.debug("umqtt client error: [%s]",e)
        return None

    for i in range(n):
        try:
            client.connect()
            return client
        except (OSError, Exception) as e:
            if i < n:
                log.debug("waiting to connect: (%d)-[%s]",i,e)
                time.sleep_ms(RETRY_DELAY)
                pass

    log.debug("failed to connect to broker: giving up!")
    return None

def connect_AP(p):
    sta_if = network.WLAN(network.STA_IF)
    sta_if.active(True)

    ap_if = network.WLAN(network.AP_IF)
    if ap_if.active() == True:
        ap_if.active(False)
        pass

    sta_if.connect(AP_LOGIN, AP_PASS)

    start = time.ticks_ms()

    #check for successful connection
    while sta_if.isconnected() != True:
        flash_led(p,2,100)
        if time.ticks_diff(time.ticks_ms(),start) > AP_TIME_OUT:
            log.debug("failed to connect to AP: giving up!")
            return None

    log.debug("connection info: [%s]",sta_if.ifconfig())
    return True

### Sensor actions

def readTemperature(pin):
    ds = ds18x20.DS18X20(onewire.OneWire(pin))
    roms = ds.scan()
    log.debug("one wire devices found: [%s]",roms)
    if len(roms) > 0:
        pass
    else:
        return 0

    temps = []
    for i in range(10):
        ds.convert_temp()
        time.sleep_ms(750)
        for rom in roms:
            log.debug("temperature: [%s]", ds.read_temp(rom))
            temps.append(ds.read_temp(rom))

    c = len(temps)
    if c > 0:
        return (sum(temps))/c
    else:
        return 0

def spray(pin,duration):
    pin.high()
    time.sleep_ms(duration)
    pin.low()

### Publish MQTT

def publish_countdown(c,n):
    for i in range(n):
        try:
            c.publish( bytes(TOPIC_COUNT,'utf-8') ,bytes(str(n-i),'utf-8') )
            time.sleep_ms(1000)
        except (OSError, Exception) as e:
            log.debug("mqtt publish error: [%s]",e)
            return

    time.sleep_us(100)

    try:
        c.publish( bytes(TOPIC_COUNT,'utf-8') ,b"zzzzzzzzz")
    except (OSError, Exception) as e:
        log.debug("mqtt publish error: [%s]",e)
        return

def publish_temperature(c,avg):
    try:
        c.publish(bytes(TOPIC_TEMP,'utf-8'), bytes(str(avg), 'utf-8'))
    except (OSError, Exception) as e:
        log.debug("mqtt publish error: [%s]",e)
        return

def goodnight():
    if DEBUG == False:
        config_deep_sleep()
        machine.deepsleep()
    else:
        machine.reset()

def main():
    pins = configure_pins()
    status = check_reset()
    #flash 2x if by deep sleep, 4x if hard reset
    flash_led(pins['led'],status)

    spray(pins['pssst'],FEED_TIME)

    status_AP = connect_AP(pins['led'])
    mqtt_client = connect_mqtt_broker(3)

    if status_AP is not None and mqtt_client is not None:
        AVG = readTemperature(pins['temp'])
        publish_temperature(mqtt_client,AVG)
        publish_countdown(mqtt_client,5)
        mqtt_client.disconnect()
    else:
        #avoid over-watering if network is down
        time.sleep_ms(TIME_OUT)
    #start/send count down and go to sleep
    goodnight()

if __name__ == "__main__":
    if DEBUG == True:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("ROSE-BUD")
    main()
