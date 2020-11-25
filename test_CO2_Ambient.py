from m5stack import *
import machine
import gc
import utime
import uos
import _thread

import wifiCfg
import ntptime
import ambient
import unit

# 変数宣言(ワーク)
Am_err              = 1     # グローバル
Disp_mode           = 0     # グローバル
LED_mode            = 0     # グローバル [-1:点灯/0:消灯/1～:点滅周期(0.1s単位)]
lcd_mute            = False # グローバル
data_mute           = False # グローバル
m5type              = 0     # グローバル [0:M5StickC、1: M5StickCPlus]

# 変数宣言(測定値)
co2                 = None  # CO2値
mhztemp             = None  # MHZ19Bの温度
temp                = None  # 温度
hum                 = None  # 湿度
pres                = None  # 気圧

# 変数宣言(定数)
am_interval         = 60    # Ambientへデータを送るサイクル（秒）
co2sensor_interval  = 5     # MH-19Bへco2測定値要求コマンドを送るサイクル（秒）
env2sensor_interval = 5     # env2hatからデータを読み出すサイクル（秒）

# 変数宣言(コンフィグ)
CO2_RED             = 1000  # co2濃度の換気閾値（ppm）のデフォルト値
TIMEOUT             = 30    # データ更新が止まった時のタイムアウト（秒）のデフォルト値
AM_CID              = None
AM_WKEY             = None
AM_RKEY             = None
AM_UID              = None
S_CO2HAT            = False
S_ENV2              = False


# @cinimlさんのファーム差分吸収ロジック
class AXPCompat(object):
    def __init__(self):
        if( hasattr(axp, 'setLDO2Vol') ):
            self.setLDO2Vol = axp.setLDO2Vol
        else:
            self.setLDO2Vol = axp.setLDO2Volt

axp = AXPCompat()


def am_thread():
    global am_interval

    global S_CO2HAT, S_ENV2

    global Am_err
    global AM_CID
    global AM_WKEY
    global AM_RKEY
    global AM_UID

    global co2, mhztemp
    global temp, hum, pres

    if (AM_CID is not None) and (AM_WKEY is not None) and (S_CO2HAT or S_ENV2) : # Ambient設定情報があった場合 / どちらかのセンサがあった場合
        import ambient
        am_co2 = ambient.Ambient(AM_CID, AM_WKEY)
        print("ambient thread start")
        data = {}
        am_tc = 0
        Am_err = 1
        while True:
            if (utime.time() - am_tc) >= am_interval :      # インターバル値の間隔でAmbientへsendする
                data.clear()
                if (co2 is not None) :
                    data["d1"] = co2
                if (mhztemp is not None) :
                    data["d2"] = mhztemp
                if (temp is not None) :
                    data["d3"] = temp
                if (hum is not None) :
                    data["d4"] = hum
                if (pres is not None) :
                    data["d5"] = pres

                if len(data) > 0 :
                    try :
                        r = am_co2.send(data)
                        print('Ambient send OK! / ' + str(r.status_code) + ' / ' + str(Am_err))
                        Am_err = 0
                        r.close()
                    except:
                        print('Ambient send ERR! / ' + str(Am_err))
                        Am_err += 1
                    am_tc = utime.time()
            utime.sleep(1)


# 時計表示/LEDスレッド関数
def disp_thread():
    global Disp_mode, Am_err
    global LED_mode

    cnt = 0
    LEDstate = True
    prevLED = None
    prev = None

    while True:
        if LED_mode > 0 :       # 点滅
            if cnt > 0 :
                cnt -= 1
            else :
                LEDstate = not LEDstate
                cnt = LED_mode
        else :                  # 点灯/消灯
            LEDstate = (LED_mode < 0)

        # LEDの状態が変わらない場合はスキップ
        if prevLED != LEDstate :
            if LEDstate :
                M5Led.on()
            else :
                M5Led.off()
            prevLED = LEDstate

        # 表示する情報が変わらない場合はスキップ
        tc = (utime.time(), Disp_mode, bool(Am_err))
        if prev != tc : 
            draw_time()
            prev = tc

        utime.sleep(0.1)


# 表示OFFボタン処理スレッド関数
def buttonA_wasPressed():
    global lcd_mute

    lcd_mute = not lcd_mute
    set_muteLCD(lcd_mute)


# 表示切替ボタン処理スレッド関数
def buttonB_wasPressed():
    global Disp_mode

    Disp_mode = (Disp_mode+1) % 2
    draw_lcd()


# LCDバックライトの輝度を設定する
def set_muteLCD(mute):
    axp.setLDO2Vol(0 if mute else 2.7)   #バックライト輝度調整（OFF/中くらい）


# 表示モード切替時の枠描画処理関数
def draw_lcd():
    global Disp_mode, m5type

    lcd.clear()
    if Disp_mode == 0 :
        if m5type == 0 :
            lcd.line(14, 0, 14, 160, lcd.LIGHTGREY)
        elif m5type == 1 :
            lcd.line(23, 0, 23, 240, lcd.LIGHTGREY)
    elif Disp_mode == 1 :
        if m5type == 0 :
            lcd.line(66, 0, 66, 160, lcd.LIGHTGREY)
        elif m5type == 1 :
            lcd.line(112, 0, 112, 240, lcd.LIGHTGREY)
    draw_co2()
    draw_temp()
    draw_time()

def draw_temp():
    global Disp_mode, m5type
    global temp, hum, pres

    print("env2:", temp, hum, pres)
    return

# CO2値表示処理関数
def draw_co2():
    global Disp_mode, m5type
    global lcd_mute, data_mute
    global CO2_RED
    global co2, mzhtemp

    if data_mute or (co2 is None) : # タイムアウトで表示ミュートされてるか、初期値のままならco2値非表示（黒文字化）
        fc = lcd.BLACK
    elif co2 >= CO2_RED :  # CO2濃度閾値超え時は文字が赤くなる
        fc = lcd.RED
        if lcd_mute == True :   # CO2濃度閾値超え時はLCD ON
            set_muteLCD(False)
    else :
        fc = lcd.WHITE
        if lcd_mute == True :
            set_muteLCD(True)
        
    if Disp_mode == 0 : # 表示回転処理
        if m5type == 0 :
            lcd.rect(15 , 0, 80, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu18, rotate = 270) # 単位(ppm)の表示
            lcd.print('ppm', 43, 55, fc)
            lcd.font(lcd.FONT_DejaVu24, rotate = 270) # co2値の表示
            lcd.print(str(co2), 40, 35 + (len(str(co2))* 24), fc)
        elif m5type == 1 :
            lcd.rect(24 , 0, 135, 240, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu24, rotate = 270) # 単位(ppm)の表示
            lcd.print('ppm', 72, 80, fc)
            lcd.font(lcd.FONT_DejaVu40, rotate = 270) # co2値の表示
            lcd.print(str(co2), 60, 40 + (len(str(co2))* 40), fc)
    elif Disp_mode == 1 :
        if m5type == 0 :
            lcd.rect(0, 0, 65, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu18, rotate = 90) # 単位(ppm)の表示
            lcd.print('ppm', 37, 105, fc)
            lcd.font(lcd.FONT_DejaVu24, rotate = 90) # co2値の表示
            lcd.print(str(co2), 40, 125 - (len(str(co2))* 24), fc)
        elif m5type == 1 :
            lcd.rect(0, 0, 111, 240, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu24, rotate = 90) # 単位(ppm)の表示
            lcd.print('ppm', 63, 160, fc)
            lcd.font(lcd.FONT_DejaVu40, rotate = 90) # co2値の表示
            lcd.print(str(co2), 75, 200 - (len(str(co2))* 40), fc)

        
# 時計表示
def draw_time():
    global Disp_mode, m5type
    global Am_err

    # Ambient通信不具合発生時は時計の文字が赤くなる
    fc = lcd.RED if Am_err else lcd.WHITE

    if Disp_mode == 0 : # 表示回転処理
        if m5type == 0 :
            lcd.rect(0 , 0, 13, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DefaultSmall, rotate = 270)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*utime.localtime()[:6]), 2, 125, fc)
        elif m5type == 1 :
            lcd.rect(0 , 0, 20, 240, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu18, rotate = 270)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*utime.localtime()[:6]), 4, 210, fc)
    elif Disp_mode == 1 :
        if m5type == 0 :
            lcd.rect(67, 0, 80, 160, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DefaultSmall, rotate = 90)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*utime.localtime()[:6]), 78, 40, fc)
        elif m5type == 1 :
            lcd.rect(113, 0, 135, 240, lcd.BLACK, lcd.BLACK)
            lcd.font(lcd.FONT_DejaVu18, rotate = 90)
            lcd.print('{}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}'.format(*utime.localtime()[:6]), 131, 30, fc)


# co2_set.txtの存在/中身チェック関数
def co2_set_filechk():
    global CO2_RED
    global TIMEOUT
    global AM_CID
    global AM_WKEY
    global AM_RKEY
    global AM_UID
    global S_CO2HAT
    global S_ENV2

    scanfile_flg = False
    for file_name in uos.listdir('/flash') :
        if file_name == 'co2_set.txt' :
            scanfile_flg = True

    if scanfile_flg :
        print('>> found [co2_set.txt] !')
        with open('/flash/co2_set.txt' , 'r') as f :
            for file_line in f :
                filetxt = file_line.strip().split(':')
                if filetxt[0] == 'CO2_RED' :
                    if int(filetxt[1]) >= 1 :
                        CO2_RED = int(filetxt[1])
                        print('- CO2_RED: ' + str(CO2_RED))
                elif filetxt[0] == 'TIMEOUT' :
                    if int(filetxt[1]) >= 1 :
                        TIMEOUT = int(filetxt[1])
                        print('- TIMEOUT: ' + str(TIMEOUT))
                elif filetxt[0] == 'AM_CID' :
                    AM_CID = str(filetxt[1])
                    print('- AM_CID: ' + str(AM_CID))
                elif filetxt[0] == 'AM_WKEY' :
                    if len(filetxt[1]) == 16 :
                        AM_WKEY = str(filetxt[1])
                        print('- AM_WKEY: ' + str(AM_WKEY))
                elif filetxt[0] == 'AM_RKEY' :
                    if len(filetxt[1]) == 16 :
                        AM_RKEY = str(filetxt[1])
                        print('- AM_RKEY: ' + str(AM_RKEY))
                elif filetxt[0] == 'AM_UID' :
                    AM_UID = str(filetxt[1])
                    print('- AM_UID: ' + str(AM_UID))
                elif filetxt[0] == 'S_CO2HAT' :
                    S_CO2HAT = filetxt[1].lower() == "true"
                    print('- S_CO2HAT: ' + str(S_CO2HAT))
                elif filetxt[0] == 'S_ENV2' :
                    S_ENV2 = filetxt[1].lower() == "true"
                    print('- S_ENV2: ' + str(S_ENV2))
    else :
        print('>> no [co2_set.txt] !')       
    return scanfile_flg


# MH-Z19B control functions
# see https://revspace.nl/MHZ19
class mhz19blib(object):
    def __init__(self):
        self.buff = bytearray(9)
        self.serial = machine.UART(1, tx=0, rx=26)
        self.serial.init(9600, bits=8, parity=None, stop=1)

    def checksum_chk(self):
        sum = 0
        for a in self.buff[1:8]:
            sum = (sum + a) & 0xff
        c_sum = 0xff - sum + 1
        if c_sum == self.buff[8]:
            return True
        else:
            print("c_sum un match!!")
            return False

    def ABCdisable(self):
        #print('send ABC disable command')
        self.serial.write(b'\xff\x01\x79\x00\x00\x00\x00\x00\x86')	# auto caliblation off
        utime.sleep(0.1)
        self.serial.readinto(self.buff)
        
    def readSensor(self):
        #print('send read CO2 command')
        self.serial.write(b'\xff\x01\x86\x00\x00\x00\x00\x00\x79')	# co2測定値リクエスト
        utime.sleep(0.1)
        len = self.serial.readinto(self.buff)
        #print('read '+str(len)+'bytes ', self.buff)

        # co2測定値リクエストの応答
        if (len < 9) or (self.buff[0] != 0xff) or not self.checksum_chk() or (self.buff[0] != 0xff) or (self.buff[1] != 0x86) :
            print('read broken frame(' + str(len) + '): ', self.buff)
            len = self.serial.readinto(self.buff)
            print('drop broken frame(' + str(len) + '): ', self.buff)
            return None

        return [self.buff[2] * 256 + self.buff[3], self.buff[4] - 40]


# メインプログラムはここから（この上はプログラム内関数）


# 画面初期化
if lcd.winsize() == (80,160) :  # M5StickC/Plus機種判定
    m5type = 0
    print('>> M5Type = M5StickC')
elif lcd.winsize() == (136,241) :
    m5type = 1
    print('>> M5Type = M5StickCPlus')


# ユーザー設定ファイル読み込み
co2_set_filechk()


# MH-19B UART設定
mhz19b = mhz19blib() if S_CO2HAT else None


# env2 unit
env2 = unit.get(unit.ENV2, unit.PORTA) if S_ENV2 else None


# ネットワーク設定
import wifiCfg
wifiCfg.autoConnect(lcdShow=True)
ntp = ntptime.client(host='jp.pool.ntp.org', timezone=9)

# 画面アップデート
set_muteLCD(lcd_mute)
draw_lcd()


# 時刻表示/LED制御スレッド起動
_thread.start_new_thread(disp_thread, ())
_thread.start_new_thread(am_thread, ())


# ボタン検出スレッド起動
btnA.wasPressed(buttonA_wasPressed)
btnB.wasPressed(buttonB_wasPressed)


# ABC disable
if mhz19b is not None :
    mhz19b.ABCdisable()


# タイムカウンタ初期値設定
co2sensor_tc = utime.time()
env2sensor_tc = utime.time()


# メインルーチン
while True :
    if env2 is not None :
        if (utime.time() - env2sensor_tc) >= env2sensor_interval : 
            env2sensor_tc = utime.time()
            temp = env2.temperature
            hum = env2.humidity
            pres = env2.pressure
            draw_temp()
            #print("env2:", temp, hum, pres)

    if mhz19b is not None :
        if (utime.time() - co2sensor_tc) >= co2sensor_interval : 
            data = mhz19b.readSensor()
            if data is not None :
                co2sensor_tc = utime.time()
                co2 = data[0]
                mzhtemp = data[1]
                data_mute = False
                draw_co2()
                #print(str(co2) + ' ppm / ' + str(temp) + 'C / ' + str(sensor_tc))
    utime.sleep(1)
    
    if not data_mute and ((utime.time() - co2sensor_tc) >= TIMEOUT) : # co2応答が一定時間無い場合はCO2値表示のみオフ
        data_mute = True
        draw_co2()

    utime.sleep(0.1)
    gc.collect()    
