from m5stack import *
import machine
import gc
import utime
import uos
import _thread
import ntptime


# 変数宣言(ワーク)
Am_err              = 1     # グローバル
Disp_mode           = 0     # グローバル
LED_mode            = 0     # グローバル [-1:点灯/0:消灯/1～:点滅周期(0.1s単位)]
lcd_mute            = False # グローバル
data_mute           = False # グローバル
m5type              = 0     # グローバル [0:M5StickC、1: M5StickCPlus]
co2                 = None  # グローバル 現在のCO2値
temp                = None  # グローバル 現在の温度

# 変数宣言(定数)
am_interval         = 60    # Ambientへデータを送るサイクル（秒）
mhz19b_interval     = 5     # MH-19Bへco2測定値要求コマンドを送るサイクル（秒）
TIMEOUT             = 30    # 何らかの事情でCO2更新が止まった時のタイムアウト（秒）のデフォルト値
CO2_RED             = 1000  # co2濃度の換気閾値（ppm）のデフォルト値
#
AM_ID               = None
AM_WKEY             = None


# @cinimlさんのファーム差分吸収ロジック
class AXPCompat(object):
    def __init__(self):
        if( hasattr(axp, 'setLDO2Vol') ):
            self.setLDO2Vol = axp.setLDO2Vol
        else:
            self.setLDO2Vol = axp.setLDO2Volt

axp = AXPCompat()


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
                M5LED.on()
            else :
                M5LED.off()
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
    draw_time()

# CO2値表示処理関数
def draw_co2():
    global Disp_mode, m5type
    global lcd_mute, data_mute
    global CO2_RED
    global co2, temp

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

    if  Disp_mode == 0 : # 表示回転処理
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


# MH-Z19Bデータのチェックサム確認関数
def checksum_chk(data):
    sum = 0
    for a in data[1:8]:
        sum = (sum + a) & 0xff
    c_sum = 0xff - sum + 1
    if c_sum == data[8]:
        return True
    else:
        print("c_sum un match!!")
        return False


# co2_set.txtの存在/中身チェック関数
def co2_set_filechk():
    global CO2_RED
    global TIMEOUT
    global AM_ID
    global AM_WKEY

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
                elif filetxt[0] == 'AM_ID' :
                    AM_ID = str(filetxt[1])
                    print('- AM_ID: ' + str(AM_ID))
                elif filetxt[0] == 'AM_WKEY' :
                    if len(filetxt[1]) == 16 :
                        AM_WKEY = str(filetxt[1])
                        print('- AM_WKEY: ' + str(AM_WKEY))
    else :
        print('>> no [co2_set.txt] !')       
    return scanfile_flg


# メインプログラムはここから（この上はプログラム内関数）


# WiFi設定
import wifiCfg
wifiCfg.autoConnect(lcdShow=True)


# 画面初期化
if lcd.winsize() == (80,160) :  # M5StickC/Plus機種判定
    m5type = 0
    print('>> M5Type = M5StickC')
elif lcd.winsize() == (136,241) :
    m5type = 1
    print('>> M5Type = M5StickCPlus')
set_muteLCD(lcd_mute)
draw_lcd()


# MH-19B UART設定
mhz19b = machine.UART(1, tx=0, rx=26)
mhz19b.init(9600, bits=8, parity=None, stop=1)


# ユーザー設定ファイル読み込み
co2_set_filechk()


# Ambient設定
am_co2 = None
if (AM_ID is not None) and (AM_WKEY is not None) : # Ambient設定情報があった場合
    import ambient
    am_co2 = ambient.Ambient(AM_ID, AM_WKEY)


# RTC設定
ntp = ntptime.client(host='jp.pool.ntp.org', timezone=9)


# 時刻表示/LED制御スレッド起動
_thread.start_new_thread(disp_thread, ())


# ボタン検出スレッド起動
btnA.wasPressed(buttonA_wasPressed)
btnB.wasPressed(buttonB_wasPressed)


# タイムカウンタ初期値設定
mhz19b_tc = utime.time()
am_tc = utime.time()


# ABC disable
mhz19b.write(b'\xff\x01\x79\x00\x00\x00\x00\x00\x86')
utime.sleep(0.1)


# メインルーチン
while True :
    if (utime.time() - mhz19b_tc) >= mhz19b_interval : # co2要求コマンド送信
        print('send read CO2 command')
        mhz19b_data = bytearray(9)
        mhz19b.write(b'\xff\x01\x86\x00\x00\x00\x00\x00\x79')   # co2測定値リクエスト
        utime.sleep(0.1)
        l = mhz19b.readinto(mhz19b_data)
        print('read '+str(l)+'bytes')
        print('read data', mhz19b_data)

        # co2測定値リクエストの応答
        if (l == 9) and (mhz19b_data[0] == 0xff) and (mhz19b_data[1] == 0x86) and (checksum_chk(mhz19b_data) == True) :    # 応答かどうかの判定とチェックサムチェック
            mhz19b_tc = utime.time()
            co2 = mhz19b_data[2] * 256 + mhz19b_data[3]
            temp = mhz19b_data[4] - 40

            data_mute = False
            draw_co2()
            print(str(co2) + ' ppm / ' + str(temp) + 'C / ' + str(mhz19b_tc))
            if (am_co2 is not None) :                           # Ambient設定情報があった場合
                if (utime.time() - am_tc) >= am_interval :      # インターバル値の間隔でAmbientへsendする
                    try :                                       # ネットワーク不通発生などで例外エラー終了されない様に try except しとく
                        r = am_co2.send({'d1': co2, 'd2': temp})
                        print('Ambient send OK! / ' + str(r.status_code) + ' / ' + str(Am_err))
                        Am_err = 0
                        r.close()
                    except:
                        print('Ambient send ERR! / ' + str(Am_err))
                        Am_err = Am_err + 1
                    am_tc = utime.time()
        utime.sleep(1)
    
    if (utime.time() - mhz19b_tc) >= TIMEOUT : # co2応答が一定時間無い場合はCO2値表示のみオフ
        data_mute = True
        draw_co2()
        
    utime.sleep(0.1)
    gc.collect()    
