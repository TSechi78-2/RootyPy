import telepot
from telepot.loop import MessageLoop
from telepot.namedtuple import InlineKeyboardMarkup, InlineKeyboardButton
import json
import requests
import time
import datetime
import paho.mqtt.client as pahoMQTT
import base64
from PIL import Image
from io import BytesIO
from requests.exceptions import HTTPError


class GreenHouseBot:
    def __init__(self,config_bot):

        self.tokenBot = json_config_bot['telegram_token']                                                  #Unique Token of the bot
        json_config_bot =  json.load(open(config_bot,'r'))
        self.bot = telepot.Bot(self.tokenBot)                                     
        self.interval = 1
        self.headers =  {'content-type': 'application/json; charset=UTF-8'}
        self.uservariables = {}
        self.registry_url = json_config_bot['url_registry']                             #Rest webservices
        self.ClientID =  json_config_bot['ID']                          #MQTT variables
        self.broker = json_config_bot['broker']
        self.port = json_config_bot['port']
        self.countdown = json_config_bot['user_inactivity_timer']                            #Value untill the user status diz is deleted to reduce the weight on the server
        self.user_check_interval = json_config_bot['user_check_interval']                    # time to which the user timers are updated
        self.iamalive_topic = json_config_bot["iamalive_topic"]                              #Topic of the service registry
        self.update_time = json_config_bot["update_time"]                                    # Frequency at wich messages to registry are sent
        self.time_zone_correction = json_config_bot['time_zone_correction']                 #  Time zone to make datetime.datetime.now function work properly
        self.num_rest_attempts = json_config_bot['number_of_requests']
        self.needed_urls = json_config_bot['needed_urls']

        self.paho_mqtt = pahoMQTT.Client(self.ClientID,True)
        self.paho_mqtt.connect(self.broker, self.port)
        self.paho_mqtt.loop_start()

        user_checker = Active_user_checker(self.user_check_interval)                                              # keeps track of the users on a timer
        bot_subscriber = Subscriber_telegram_bot(self.ClientID+'_subscriber',self.port,self.broker,self,json_config_bot['sub_topics'])          # Mqtt subscriber that receives messages and gives the to the bot
        self.registry_interface = Registry_interface(self.registry_url,self.num_rest_attempts,self)
        iamalive = Iamalive(self.iamalive_topic,self.update_time,self.ClientID,self.port,self.broker,self.registry_interface)             #makes the microservice visible to the user
        self.set_needed_urls(iamalive.ask_for_urls(self.needed_urls))
        print(self.needed_urls)
        self.adaptor_interface = Adaptor_interface(self.needed_urls['adaptor'],self.num_rest_attempts)
        self.report_generator_interface = Report_manager(self.needed_urls['Report_generator'],self,self.num_rest_attempts)
        self.irrigation_manager = Irrigation_manager(self)
        self.led_manager = Led_manager(self)
        self.repeated_function_interval = json_config_bot['repeated_function_interval']      # Frequency at which functions in a loop are executed

        #Dictionaries with the function to perform after a certain specification which will be written in query_list[1]
        diz_plant = {'inventory':self.choose_plant,'add':self.add_planttoken,'back':self.manage_plant,'create':self.choose_plant_type,'change':self.change_plant_name,'choose':self.remove_old_name_add_new}  #managing plants
        diz_actions = { 'water':self.irrigation_manager.water_plant, 'ledlight':self.led_manager.led_management,'reportmenu':self.report_generator_interface.set_frequency_or_generate}   #actions to take care of the plant
        diz_led = {'setpercentage':self.led_manager.set_led_percentage,'setmanualmodduration':self.led_manager.set_led_manual_mode_duration,'switch':self.led_manager.led_switch,'off':self.led_manager.instant_switch_off,'change':self.led_manager.led_change}      # control the led light
        diz_newuser = {'confirmname':self.add_passwd,'newname':self.add_user,'confirmpwd':self.confirm_pwd,'confirmtoken':self.add_plant,'newpsw':self.add_passwd,'newtkn':self.add_planttoken,'newplantname':self.add_plant,'sign_up':self.add_user,'transferaccount':self.transfer_usern,'back':self. new_user_management}
        diz_removeplant = {'choose':self.remove_plant,'plantname':self.confirmed_remove_plant}
        diz_report = {'generate':self.report_generator_interface.generate_instant_report,'settings':self.report_generator_interface.set_report_frequency}
        self.diz = { 'actions':diz_actions , 'led':diz_led,'plant':diz_plant,'removeplant':diz_removeplant,'newuser':diz_newuser,'report':diz_report}     #dictionary with dictionaries


        MessageLoop(self.bot, {'chat': self.on_chat_message,'callback_query': self.on_callback_query}).run_as_thread()    #manages incoming telegram messages and callbacks


        while True:
            time.sleep(self.repeated_function_interval)
            iamalive.check_and_publish()                                                      #if enough seconds have passed sends message
            self.uservariables = user_checker.updating_user_timer(self.uservariables,self)    # if a user hasn't interacted for enought time deletes them from self.uservariables
            bot_subscriber.empty_queue()                                                      # Manages mqtt messages in the queue



#---------------------------------------------------- Bot callbacks ----------------------------------------------------------------------

    

    def on_chat_message(self, msg):   
        content_type, chat_type, chat_ID = telepot.glance(msg)                   # Who sent the message
        if chat_ID in self.uservariables.keys():                                 # checks if the user was recently active
            self.restarting_user_timer(chat_ID,self.countdown)                   # restarts the timer of activity associated to the user
        else:
            pass
        message = msg['text']                                                    # Actual text of the message
        msg_id = telepot.message_identifier(msg)                       
        self.bot.deleteMessage(msg_id)                                           #Deletes user's text
        if message == "/start":                                                  #starts the bot
            self.start_user_status(chat_ID)                                      # Create a voice at  key chat_id in uservariables
            if self.registry_interface.is_new_user(chat_ID):
                print('new user detected')
                self.new_user_management(chat_ID)                                # Menu for new users
            else:
                self.choose_plant(chat_ID)                                      # If not new show the plants to the user

        elif  'listeningfortime' in self.get_uservariables_chatstatus(chat_ID):                     #Messages from users used in the functions
            self.led_manager.confirm_manual_mode_duration(message,chat_ID)
        elif "listeningforobswindow" in self.get_uservariables_chatstatus(chat_ID) :
            self.led_manager.set_light_time(message,chat_ID,self.get_uservariables_chatstatus(chat_ID).split('&')[1],self.get_uservariables_chatstatus(chat_ID).split('&')[2])
        elif 'listeningforledpercentage' in self.get_uservariables_chatstatus(chat_ID) :
            self.led_manager.check_light_percentage(message,chat_ID)
        elif self.get_uservariables_chatstatus(chat_ID).split('&')[0] == 'listeningforplantname':
            self.eval_plant_name(chat_ID,message,self.get_uservariables_chatstatus(chat_ID).split('&')[1],self.get_uservariables_chatstatus(chat_ID).split('&')[2])
        elif self.get_uservariables_chatstatus(chat_ID) == 'listeningforuser':
            self.eval_username(chat_ID,message)
        elif self.get_uservariables_chatstatus(chat_ID).split('&')[0]== 'listeningforpwd':
            self.eval_pwd(chat_ID,self.get_uservariables_chatstatus(chat_ID).split('&')[1],message)
        elif 'listeningforwaterpercentage' in  self.get_uservariables_chatstatus(chat_ID):
            self.irrigation_manager.eval_water_percentage(chat_ID,message)
        elif self.get_uservariables_chatstatus(chat_ID) == 'listeningfortoken':
            self.eval_token(chat_ID,message)
        elif self.get_uservariables_chatstatus(chat_ID) == 'listeningfortransfername':
            self.transfer_password(chat_ID,msg['text'])
        elif 'listeningfortransferpwd' == self.get_uservariables_chatstatus(chat_ID).split('&')[0]:            
            if self.confirm_transfer(chat_ID, self.get_uservariables_chatstatus(chat_ID).split('&')[1],msg['text']):
                msg_id = self.bot.sendMessage(chat_ID, text='Account migrated correctly')['message_id']
                self.set_uservariables_chatstatus(chat_ID,'start')
                self.remove_previous_messages(chat_ID)
                self.update_message_to_remove(msg_id,chat_ID)
                self.choose_plant(chat_ID)
            else:
                msg_id = self.bot.sendMessage(chat_ID, text='Wrong credentials')['message_id']
                self.remove_previous_messages(chat_ID)
                self.update_message_to_remove(msg_id,chat_ID)
                self.new_user_management(chat_ID)

    def on_callback_query(self,msg):

         #deals with the answers from the buttons
        query_ID , chat_ID , query_data = telepot.glance(msg,flavor='callback_query')           # who sent the message and whats in the query
        if chat_ID in self.uservariables.keys():
            self.restarting_user_timer(chat_ID,self.countdown)     
            self.set_uservariables_chatstatus(chat_ID,'start')
            query_list = query_data.split('&')                             # splits the query from the callback_data, function_to_call is extracted from the dictionaries
            if query_list[0] == 'plant':
                if query_list[1] not in self.diz['plant'].keys():
                    self.manage_plant(chat_ID,query_list[1])
                else:
                    function_to_call = self.diz['plant'][query_list[1]]
                    if query_list[1] == 'create':
                        function_to_call(chat_ID,query_list[2],query_list[3])
                    elif query_list[1] == 'choose':
                        function_to_call(chat_ID,query_list[2],query_list[3])
                    elif query_list[1] == 'back':
                        function_to_call(chat_ID,query_list[2])
                    else:
                        function_to_call(chat_ID)
            elif query_list[0] == 'command':
                function_to_call = self.diz['actions'][query_list[1]]
                function_to_call(chat_ID,query_list[2])
            elif query_list[0] == 'led':
                function_to_call = self.diz['led'][query_list[1]]
                function_to_call(chat_ID,query_list[2])
            elif query_list[0] == 'newuser':
                print('new user')
                function_to_call = self.diz['newuser'][query_list[1]]
                if query_list[1] == 'confirmname' or query_list[1] == 'confirmtoken':
                    function_to_call(chat_ID,query_list[2])
                elif query_list[1] == 'confirmpwd':
                    function_to_call(chat_ID,query_list[2],query_list[3])
                else:
                    function_to_call(chat_ID)
            elif query_list[0] == 'report':
                function_to_call = self.diz['report'][query_list[1]]
                function_to_call(chat_ID,query_list[2])
            elif query_list[0] == 'f_settings':
                self.registry_interface.set_new_report_frequency(chat_ID,query_list[1],query_list[2])
            elif query_list[0] == 'time':
                self.led_manager.change_time(chat_ID,query_list[1],query_list[2])
            elif query_list[0] == 'inventory':
                self.choose_plant(chat_ID)
            elif query_list[0]== 'changeplantname':
                self.confirmed_change_name(chat_ID,query_list[1])
            elif query_list[0] == 'plant_type':
                self.create_plant(chat_ID,query_list[2],query_list[1],query_list[3])
            elif query_list[0] == 'removeplant':
                if query_list[1] not in self.diz['removeplant'].keys():
                    function_to_call = self.diz['removeplant']['plantname']
                    function_to_call(chat_ID,query_list[1])
                else:
                    function_to_call = self.diz['removeplant'][query_list[1]]
                    function_to_call(chat_ID)
        else:
            #When the user status its deleted the user isinvited to restart the bot
            msg_id = self.bot.sendMessage(chat_ID, text='Too long since last interaction restart the bot with /start')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)


    def set_needed_urls(self,needed_urls):
        self.needed_urls = needed_urls

    def set_uservariables_chatstatus(self,chatID,new_status):
        self.uservariables[chatID]['chatstatus'] = new_status

    def get_uservariables_chatstatus(self,chatID):
        return self.uservariables[chatID]['chatstatus']
   #----------------------------------------------------- Managing user connected -------------------------------------------------


    # Initialize or update the status of a user identified by chat_ID.
    # If the chat_ID does not exist in the chatstatus dictionary, it creates a new entry with 'chatstatus' set to 'start'.
    def start_user_status(self, chat_ID):
        if chat_ID not in self.uservariables.keys():
            self.uservariables[chat_ID] = {}  # Initialize a new entry for the user
            self.set_uservariables_chatstatus(chat_ID,'start') # Set the chatstatus for the user to 'start'
            self.uservariables[chat_ID]['timer'] = self.countdown # Starts the "activity" countdown   
            print(f'{chat_ID} connected ')


    # Update the timer for a user identified by chat_ID with a new countdown value.
    def restarting_user_timer(self, chat_ID, countdown):
        self.uservariables[chat_ID]['timer'] = countdown  # Set the timer for the user to the given countdown value

    #-------------------------------------------------  manage a plant  ---------------------------

    def choose_plant(self,chat_ID,keep_prev = False):                       # plant selection from the inventory of the user
        buttons = []
        try:
            user_plants = self.registry_interface.get_plant_for_chatID(chat_ID)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get your plants, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        userid = self.registry_interface.get_username_for_chat_ID(chat_ID)
        print(user_plants)
        for element in user_plants:                           # Create keyboard
            try:
                element_code = self.registry_interface.get_plant_code_from_plant_name(userid,element)         #gets the plantcode for every plant name
            except:
                msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get full plant list, try again later')
                self.update_message_to_remove(msg_id,chat_ID)
            buttons.append(InlineKeyboardButton(text=f'{element}', callback_data='plant&'+element_code))
        buttons.append(InlineKeyboardButton(text=f'add plant', callback_data='plant&add'))                          #allows the user to create plant
        buttons.append(InlineKeyboardButton(text=f'remove plant', callback_data='removeplant&choose'))              # allows the user to remove the plant
        buttons.append(InlineKeyboardButton(text=f'change plant name', callback_data='plant&change'))              # Changes the plant name
        buttons = [buttons]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='Choose one of your plants', reply_markup=keyboard)['message_id']
        if keep_prev == False:                                       #flag that removes the previouse messages or not
            self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)

    def manage_plant(self,chat_ID,plantcode):                       #generate a report on the status of the plant and allows you to perform change of the led or water

        userid = self.registry_interface.get_username_for_chat_ID(chat_ID)
        # Extracts moster recent data uploaded in the database
        lux_sensor = json.loads(self.adaptor_interface.get_data(userid,plantcode,'light',1).text)
        lamp_emission =  json.loads(self.adaptor_interface.get_data(userid,plantcode,'current_intensity',1).text)
        moisture =  json.loads(self.adaptor_interface.get_data(userid,plantcode,'moisture',1).text)
        tank_level =  json.loads(self.adaptor_interface.get_data(userid,plantcode,'tankLevel',1).text)
        # Managing the initialitation of the kit
        if len(lux_sensor) > 0:
            actual_lux = round(lux_sensor[-1]['v'],2)
            str_lux = f'light received: {actual_lux} lux'
        else:
            str_lux = 'no sensor data for light sensor'
        if len(lamp_emission) > 0:
            actual_emission = round(lamp_emission[-1]['v'],2)
            str_lamp = f'current lamp intensity: {actual_emission} %'
        else:
            str_lamp = f'no data on lamp intensity'
        if len(moisture) > 0:
            actual_moisture = round(moisture[-1]['v'],2)
            str_moisture = f'actual moisture: {actual_moisture} '
        else:
            str_moisture = f'no sensor data on moisture'
        if len(tank_level) > 0:
            actual_tank_level = round(tank_level[-1]['v'],2)
            str_tank = f'actual tank level {actual_tank_level}'
        else:
            str_tank = 'no sensor data on tank level'
    
        msg_id = self.bot.sendMessage(chat_ID,text = str_lux+'\n'+str_lamp+'\n'+str_moisture+'\n'+str_tank)['message_id']

        self.update_message_to_remove(msg_id,chat_ID)
        # Menu of actions for a plant
        buttons = [[InlineKeyboardButton(text=f'water 💦', callback_data=f'command&water&{plantcode}'), InlineKeyboardButton(text=f'led light 💥', callback_data=f'command&ledlight&{plantcode}'), InlineKeyboardButton(text=f'report', callback_data=f'command&reportmenu&{plantcode}'),InlineKeyboardButton(text=f'back ', callback_data='inventory&start')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='What do you want to do?', reply_markup=keyboard)['message_id']
        self.update_message_to_remove(msg_id,chat_ID)

 # ----------------------------------------------------- sign up ------------------------------------------------
  

    def new_user_management(self,chat_ID):       
        #Makes the user choose between sign up and transfer an already existing account from nodered
        buttons = [[InlineKeyboardButton(text=f'new user', callback_data='newuser&sign_up'), InlineKeyboardButton(text=f'transfer account', callback_data='newuser&transferaccount')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='What do you want to do?', reply_markup=keyboard)['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)

    def register_user(self,chat_ID,userid,pwd):
        # Register the user in the registry through a post request
        body = {'userId' : userid,'password':pwd,'chatID':chat_ID}
        r =self.post_response(self.registry_url+'/addu',body)
        output = json.loads(r.text)
        self.remove_previous_messages(chat_ID)
        if self.manage_invalid_request(chat_ID,output):
            msg_id = self.bot.sendMessage(chat_ID,text = 'Something went wrong, try restarting the bot with /start')
            self.update_message_to_remove(msg_id,chat_ID)

    def add_user(self,chat_ID):
        #Give the user the possiblity to write his username
        self.set_uservariables_chatstatus(chat_ID,'listeningforuser')
        buttons = [[InlineKeyboardButton(text=f'🔙', callback_data='newuser&back')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='Choose a username',reply_markup=keyboard)['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        print(f'waiting for name from {chat_ID}')

    def eval_username(self,chat_ID,message):
        #Checks if in the name are present illegal characters
        if any(char in message.strip() for char in '&;:",/\'{}[]'):
            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} is a invalid name contains \'&\' or \';\' ')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
        else:
            buttons = [[InlineKeyboardButton(text=f'confirm', callback_data=f'newuser&confirmname&{message.strip()}'), InlineKeyboardButton(text=f'abort', callback_data='newuser&newname')]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} it\'s a valid name \nwould you like to confirm?',reply_markup=keyboard)['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
            self.set_uservariables_chatstatus(chat_ID,'start')
 


    def add_passwd(self,chat_ID,username):
        # Gives the user the possiblity to write his password
        buttons = [[InlineKeyboardButton(text=f'🔙', callback_data='newuser&back')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='Choose a password',reply_markup=keyboard)['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,f'listeningforpwd&{username}')
        print(f'waiting for password from {chat_ID}')

    def eval_pwd(self,chat_ID,userid,message): 
        # Checks if in the password contains invalid characters
        if any(char in message.strip() for char in '&;:",/\'{}[]'):
            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} is a invalid name contains \'&\' or \';\' ')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
        else:
            buttons = [[InlineKeyboardButton(text=f'confirm', callback_data=f'newuser&confirmpwd&{userid}&{message}'), InlineKeyboardButton(text=f'abort', callback_data='newuser&newpsw')]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} it\'s a valid password \nwould you like to confirm?',reply_markup=keyboard)['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
            self.set_uservariables_chatstatus(chat_ID,'start')


    def confirm_pwd(self,chat_ID,userid,pwd):
        # Once the password is confirmed register the user and asks for the user first plant
        self.register_user(chat_ID,userid,pwd)
        self.add_planttoken(chat_ID)

# ---------------------------------------- REST management ----------------------------------------------------        



    def manage_invalid_request(self,chat_ID,req_output):
        # Gives the reason of failure of requests
        if req_output['code'] != 200:
            msg_id = self.bot.sendMessage(chat_ID,text = f'{req_output['message']}')['message_id']
            self.update_message_to_remove(msg_id,chat_ID)
            return True
        else:
            return False

    def get_response(self,url):
        # Tries a number of times a get request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

    def put_response(self,url,body):
        # Tries a number of times a put request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.put(url,json = body)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

    def post_response(self,url,body):
        # Tries a number of times a post request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.post(url,json = body)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None


#------------------------------------------------- Adding a plant ----------------------------------------------#        

    def add_plant(self,chat_ID,token):  
        # allows self.on_chat_message() to stop listen to commands and listen for names
        msg_id = self.bot.sendMessage(chat_ID, text='Send new plant name in the chat')['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,f'listeningforplantname&create&{token}')

    def eval_plant_name(self,chat_ID,mex,mode,plant = ''):            
        #Checks if the name is already used or other exceptions and makes you confirm
        try:
            user_plants = self.registry_interface.get_plant_for_chatID(chat_ID)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get plant code, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        name_set = set(user_plants)
        if mex.strip() in name_set:
            msg_id = self.bot.sendMessage(chat_ID,text =f'{mex} already exists')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
        elif any(char in mex.strip() for char in '&;:",/\'{}[]'):
            msg_id = self.bot.sendMessage(chat_ID,text =f'{mex} is a invalid name contains \'&,,,:,;,/,[,] ')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
        else:
            buttons = [[InlineKeyboardButton(text=f'confirm', callback_data='plant&'+ mode +'&'+mex+'&'+plant), InlineKeyboardButton(text=f'abort', callback_data='plant&inventory')]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            msg_id = self.bot.sendMessage(chat_ID,text =f'{mex} it\'s a valid name \nwould you like to confirm?',reply_markup=keyboard)['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
            self.set_uservariables_chatstatus(chat_ID,'start')
    
    def create_plant(self,chat_ID,plantname,plant_type,plantcode):        
         # Writes the name to the catalog
        body = {'userId' : self.registry_interface.get_username_for_chat_ID(chat_ID),'plantId':plantname,'plantCode':plantcode,'type':plant_type}
        r = self.post_response(self.registry_url+'/addp', body)
        output = json.loads(r.text)
        flag_keep_messages = self.manage_invalid_request(chat_ID,output)
        self.choose_plant(chat_ID,keep_prev = flag_keep_messages)

    def choose_plant_type(self,chat_ID,plantname,plantcode):
        #Choose the type of the plant
        available_plant_types = self.registry_interface.get_available_plant_types()
        buttons = []
        for pt in available_plant_types:
            button = [InlineKeyboardButton(text=f'{pt}', callback_data=f'plant_type&{pt}&{plantname}&{plantcode}')]
            buttons.append(button)
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID,text =f'choose plant type:',reply_markup=keyboard)['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)

    def eval_token(self,chat_ID,message):
        #Checks if the token is in the right format
        message= str(message.strip())
        if not (message[0].isalpha() and message[1].isalpha()) and not all(char.isdigit() for char in message[2:]) or len(message) != 5:

            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} is a invalid plant-code')['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
        else:
            # makes the user go back of confirm
            buttons = [[InlineKeyboardButton(text=f'confirm', callback_data=f'newuser&confirmtoken&{message.strip()}'), InlineKeyboardButton(text=f'abort', callback_data='newuser&newtkn')]]
            keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
            msg_id = self.bot.sendMessage(chat_ID,text =f'{message} it\'s your token \nwould you like to confirm?',reply_markup=keyboard)['message_id']
            self.remove_previous_messages(chat_ID)
            self.update_message_to_remove(msg_id,chat_ID)
            self.set_uservariables_chatstatus(chat_ID,'start')

    def add_planttoken(self,chat_ID):
        # Starts listening for the user to write its plant code
        msg_id = self.bot.sendMessage(chat_ID, text='Insert the token of your pot, it\'s written on the bottom of the pot, it starts with two letters followed by three of numbers')['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,'listeningfortoken')
        print(f'waiting for  pot token from {chat_ID}')


#--------------------------------------------------------- Adapt user from NodeRed ----------------------------------------------------

    def transfer_usern(self,chat_ID):
        # Listens for a username
        msg_id = self.bot.sendMessage(chat_ID, text='insert you username')['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,'listeningfortransfername')
        print(f'waiting for username to transfer account for {chat_ID}')

    def transfer_password(self,chat_ID,userid):
        # Listens for a passwords
        msg_id = self.bot.sendMessage(chat_ID, text='insert your password')['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,f'listeningfortransferpwd&{userid}')
        print(f'waiting for username to transfer account for {chat_ID}')

    def confirm_transfer(self,chat_ID,username,pwd):
        # Asks the server to confirm if such username and password have a correspondance
        f = False
        users = self.registry_interface.get_users()
        for user in users:
            if user['userId'] == username and user['password'] == pwd:
                f = True
                body = {"userId":username, 'chatID':chat_ID}
                r = self.put_response(self.registry_url+'/transferuser',body)
                if self.manage_invalid_request(chat_ID,json.loads(r.text)):
                    msg_id = self.bot.sendMessage(chat_ID,'something went wrong try restarting the bot with /start')
                    self.update_message_to_remove(msg_id,chat_ID)
        return f


#--------------------------------------- Plant Removal ------------------------------------------------------------------------------------

    def remove_plant(self,chat_ID):
        #Asks for safety if the user really wants to delete the user
        msg_id = self.bot.sendMessage(chat_ID,text = f"Be careful!\n You're trying to remove a plant")['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        buttons = []
        try:
            plant_list = self.registry_interface.get_plant_for_chatID(chat_ID)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get plant code, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        for element in plant_list:
            buttons.append(InlineKeyboardButton(text=f'{element}', callback_data='removeplant&'+element))
        buttons.append(InlineKeyboardButton(text=f'🔙', callback_data='plant&inventory'))
        buttons = [buttons]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text='Choose the plant you\'d like to remove', reply_markup=keyboard)['message_id']
        self.update_message_to_remove(msg_id,chat_ID)


    def confirmed_remove_plant(self,chat_ID,plantname):#*
        userid = self.registry_interface.get_username_for_chat_ID(chat_ID)
        try:
            plantcode = self.registry_interface.get_plant_code_from_plant_name(userid,plantname)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get plant code, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        r = requests.delete(self.registry_url+f'/rmp/{userid}/{plantcode}',headers = self.headers)
        print(f'delete request sent at {self.registry_url}/rmp')
        self.manage_invalid_request(chat_ID,json.loads(r.text))
        msg_id = self.bot.sendMessage(chat_ID,text = f"You correctly removed {plantname}")['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.choose_plant(chat_ID)

#----------------------------------------------------------- Change plant name ---------------------------------------------------------------
    
    def change_plant_name(self,chat_ID):   
        # Shows a menu where the user can choose the plant he would like to rename
        buttons = []
        try:
            plant_list = self.registry_interface.get_plant_for_chatID(chat_ID)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get plant code, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        for element in plant_list:
            buttons.append(InlineKeyboardButton(text=f'{element}', callback_data='changeplantname&'+element))
        buttons.append(InlineKeyboardButton(text=f'🔙', callback_data='plant&inventory'))
        buttons = [buttons]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.bot.sendMessage(chat_ID, text="Chose the plant whose name you'd like to change", reply_markup=keyboard)['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)

    def confirmed_change_name(self,chat_ID,plantname):   
        # Starts listening for the name he'd like to use to rename the plant                   
        msg_id = self.bot.sendMessage(chat_ID, text='Send plant name in the chat')['message_id']
        self.remove_previous_messages(chat_ID)
        self.update_message_to_remove(msg_id,chat_ID)
        self.set_uservariables_chatstatus(chat_ID,f'listeningforplantname&choose&{plantname}')

    def remove_old_name_add_new(self,chat_ID,newname,oldname):
        # Makes a put request to change the name of the plant in the catalog
        userid = self.registry_interface.get_username_for_chat_ID(chat_ID)
        try:
            plant_code = self.registry_interface.get_plant_code_from_plant_name(userid,oldname)
        except:
            msg_id = self.bot.sendMessage(chat_ID,text = 'unable to get plant code, action blocked')
            self.update_message_to_remove(msg_id,chat_ID)
        body = {"plantCode":plant_code,'new_name':newname}
        r = self.put_response(self.registry_url+'/modifyPlant',body)
        output = json.loads(r.text)
        flag_remove_mex = self.manage_invalid_request(chat_ID,output)
        self.choose_plant(chat_ID,flag_remove_mex)
        msg_id = self.bot.sendMessage(chat_ID, text=f'You changed name to {oldname} into {newname}')['message_id']
        self.update_message_to_remove(msg_id,chat_ID)



#----------------------------------------------- removes messages from bot --------------------------------------

    def update_message_to_remove(self, msg_id, chat_ID):
        # Adds to the uservariables the messages that are going to be deleted
        if msg_id is not None:
            if 'messages_to_remove' not in self.uservariables[chat_ID].keys():
                self.uservariables[chat_ID]['messages_to_remove'] = [msg_id]
            else:
                self.uservariables[chat_ID]['messages_to_remove'].append(msg_id)


    def remove_previous_messages(self, chat_ID):
        # Removes all the messages stored in the list self.uservariables[chat_ID]['messages_to_remove']
        if 'messages_to_remove' in self.uservariables[chat_ID].keys():
            for msg_id in self.uservariables[chat_ID]['messages_to_remove']:
                if msg_id is not None:
                    try:
                        self.bot.deleteMessage((chat_ID, msg_id))
                    except telepot.exception.TelegramError as e:
                        print(f"Failed to delete message {msg_id}: {e}")
                else:
                    print(f"Invalid msg_id: {msg_id} for chat_ID: {chat_ID}, skipping deletion")
            
            self.uservariables[chat_ID]['messages_to_remove'] = []

  


#-------------------------------------------------Handle mqtt messages ---------------------------------------

    def Handle_report(self, msg):
        # Extract the payload from the incoming message
        payload = msg.payload
        print(f"Received {payload} on topic {msg.topic}")

        # Parse the topic to extract the user and plant identifiers
        user = msg.topic.split('/')[2]
        plant = msg.topic.split('/')[3]

        # Decode the JSON payload to a dictionary
        payload_dict = json.loads(payload.decode('utf-8'))
        
        # Get the chat ID for the given username
        chat_ID = self.registry_interface.get_chatID_for_username(user)
            
        # Extract and decode the base64-encoded image from the payload
        image_base64 = payload_dict["e"][0]["v"]
        image_data = base64.b64decode(image_base64)
        
        # Get the plant name using the plant code
        plantname = self.registry_interface.get_plantname_for_plantcode(plant)

        # Construct the message to be sent along with the image
        message = plantname + ' :' + payload_dict["e"][1]["v"]

        # Load the image into a BytesIO stream for sending
        image = Image.open(BytesIO(image_data))
        bio = BytesIO()
        image.save(bio, format='PNG')
        bio.seek(0)

        # Send the image and message using the bot
        self.bot.sendPhoto(chat_ID, bio, caption=message)

    def Handle_water_tank_alert(self, msg):
        # Extract the topic from the incoming message
        topic = msg.topic
        
        # Parse the topic to extract the user and plant identifiers
        user = topic.split('/')[2]
        plant = topic.split('/')[3]
            
        # Get the chat ID for the given username
        chat_ID = self.registry_interface.get_chatID_for_username(user)
        
        # Get the plant name using the plant code
        plantname = self.registry_interface.get_plantname_for_plantcode(plant)

        # Send an alert message about the water tank using the bot
        self.bot.sendMessage(chat_ID, text=f'Watchout tank almost empty for {plantname}')

#----------------------------------------------------- Lamp management ---------------------------------------------------------------- 

class Led_manager():

    def __init__(self,main_bot):
        self.main_bot = main_bot
        pass

    def led_management(self, chat_ID,plantcode):              # Gives you the possiblity to change light schedule of auto and manual mode and to switch off
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text="You chose to manage the LED")['message_id']
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)
        buttons = [[ InlineKeyboardButton(text=f'switch off 🔌', callback_data=f'led&off&{plantcode}'), InlineKeyboardButton(text=f'led manual 💡', callback_data=f'led&setpercentage&{plantcode}'),InlineKeyboardButton(text=f'change automatic mode', callback_data=f'led&change&{plantcode}'),InlineKeyboardButton(text=f'🔙', callback_data=f'plant&back&{plantcode}')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='What do you want to do?', reply_markup=keyboard)['message_id']
        self.main_bot.update_message_to_remove(msg_id,chat_ID)

    def set_led_percentage(self,chat_ID,plantcode):
        # Asks the user for led percentage
        self.main_bot.set_uservariables_chatstatus(chat_ID,f'listeningforledpercentage&{plantcode}')
        print(f'started listening for light percentage from {chat_ID}')
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Insert desired percentage of light as an integer number ')['message_id']
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)

    def check_light_percentage(self, msg, chat_ID):
        # Checks if the percentage give n by the user respects certain constraints
        clean_mex = msg.strip()
        
        try:
            # Attempt to convert the cleaned message to a float
            percentage = float(clean_mex)
            
            # Check if the percentage is within the valid range
            if 0 <= percentage <= 100:
                plantcode = self.main_bot.get_uservariables_chatstatus(chat_ID).split('&')[1]
                self.main_bot.set_uservariables_chatstatus(chat_ID,'start')
                self.set_led_manual_mode_duration(chat_ID,plantcode,percentage)
            else:
                msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Percentage must be between 0 and 100')['message_id']
                self.main_bot.remove_previous_messages(chat_ID)
                self.main_bot.update_message_to_remove(msg_id,chat_ID)
        except ValueError:
            # If conversion to float fails, send an error message
            msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Invalid percentage format')['message_id']
            self.main_bot.remove_previous_messages(chat_ID)
            self.main_bot.update_message_to_remove(msg_id,chat_ID)



    def set_led_manual_mode_duration(self,chat_ID,plantcode,percentage):
        #  Asks the user when he'd like to switch off the light once he sets the percentage of the activation
        self.main_bot.set_uservariables_chatstatus(chat_ID,f'listeningfortime&{plantcode}&{percentage}')
        print(f'started listening for time for {plantcode}')
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Insert when the light should switch off in format hh:mm')['message_id']
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)

    def get_next_occurrence_unix_timestamp(self,time_str,time_zone_correction):
        # Computes the unix timestamp of a certain time in format hh:mm, if such time it's before the actual timestamps writes it in the next day

        # Parse the input time string into hours and minutes 
        hours, minutes = map(int, time_str.split(":"))
        
        # Get the current time
        current_time = time.localtime()
        
        # Create a struct_time object for the target time today
        target_time_today = time.struct_time((
            current_time.tm_year,  # Year
            current_time.tm_mon,   # Month
            current_time.tm_mday,  # Day
            hours,                 # Hour
            minutes,               # Minute
            0,                     # Second
            current_time.tm_wday,  # Weekday
            current_time.tm_yday,  # Yearday
            current_time.tm_isdst  # Daylight saving time flag
        ))
        
        # Convert the struct_time to a Unix timestamp
        target_timestamp_today = time.mktime(target_time_today)
        
        # Get the current Unix timestamp
        current_timestamp = time.time()
        
        # If the target time has already passed today, compute the Unix timestamp for the same time tomorrow
        if target_timestamp_today <= current_timestamp:
            # Create a struct_time object for the target time tomorrow
            target_time_tomorrow = time.struct_time((
                current_time.tm_year,  # Year
                current_time.tm_mon,   # Month
                current_time.tm_mday + 1,  # Next day
                hours,                 # Hour
                minutes,               # Minute
                0,                     # Second
                (current_time.tm_wday + 1) % 7,  # Weekday (next day)
                current_time.tm_yday + 1,  # Yearday (next day)
                current_time.tm_isdst  # Daylight saving time flag
            ))
            target_timestamp_tomorrow = time.mktime(target_time_tomorrow)
            
            return target_timestamp_tomorrow + time_zone_correction*3600
        
        return target_timestamp_today + time_zone_correction*3600

    def confirm_manual_mode_duration(self,mex,chat_ID):
        # Checks that given thime satisfies certain constraints
        mex=mex.strip()
        if len(mex) != 5 :
            self.main_bot.bot.send_message(chat_ID,text = 'invalid message')
        else:
            if mex[2] == ':' and mex[0].isdigit() and mex[1].isdigit() and mex[3].isdigit() and mex[4].isdigit():
                hour = int(mex.split(':')[0])
                minute = int(mex.split(':')[1])
            else:
                msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Invalid message')['message_id']
                self.main_bot.remove_previous_messages(chat_ID)
                self.main_bot.update_message_to_remove(msg_id,chat_ID)
            if hour >= 0 and hour <= 24 and minute >= 0 and minute <= 59:
                m_mode_duration = self.get_next_occurrence_unix_timestamp(mex,self.main_bot.time_zone_correction)
                print(f'stopped listening for time {chat_ID}')
                plantcode = self.main_bot.get_uservariables_chatstatus(chat_ID).split('&')[1]
                percentage = self.main_bot.get_uservariables_chatstatus(chat_ID).split('&')[2]
                self.main_bot.set_uservariables_chatstatus(chat_ID,'start')
                msg_id = self.main_bot.bot.sendMessage(chat_ID, text=f"light will be switched off at {mex}")['message_id']
                self.main_bot.remove_previous_messages(chat_ID)
                self.main_bot.update_message_to_remove(msg_id,chat_ID)
                self.led_switch(chat_ID,plantcode,percentage,m_mode_duration)
            else:
                msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Invalid message')['message_id']     
                self.main_bot.remove_previous_messages(chat_ID)  
                self.main_bot.update_message_to_remove(msg_id,chat_ID)


    def led_change(self,chat_ID,plantcode):            
         # Makes you choose to change the start time or the stop time
        userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
        time_start,time_end = self.main_bot.registry_interface.get_time_start_and_time_end_from_chatId(userid)
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text=f"start time {time_start}\nend time {time_end}")['message_id']
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)
        buttons = [[InlineKeyboardButton(text=f'change start ⏰', callback_data=f'time&start&{plantcode}'), InlineKeyboardButton(text=f'change stop ⏰', callback_data=f'time&end&{plantcode}'),InlineKeyboardButton(text=f'🔙', callback_data=f'plant&back&{plantcode}')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='What do you want to change?', reply_markup=keyboard)['message_id']
        self.main_bot.update_message_to_remove(msg_id,chat_ID)


    def change_time(self,chat_ID,timest,plantcode):         
        # Listens for the new value of auto mode, bot start of end, on the basi of timest variable
        self.main_bot.set_uservariables_chatstatus(chat_ID,f'listeningforobswindow&{timest}&{plantcode}')
        print(f'started listening for time for {chat_ID}')
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Insert time in format hh:mm')['message_id']
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)

    def set_light_time(self,mex,chat_ID,checkp,plantcode):   
        # Extracts time of the auto mode and assigns it to the plant in the registry
        mex=mex.strip()
        if mex[2] == ':' and mex[0].isdigit() and mex[1].isdigit() and mex[3].isdigit() and mex[4].isdigit():
            hour = int(mex.split(':')[0])
            minute = int(mex.split(':')[1])
        else:
            msg_id = self.main_bot.bot.sendMessage(chat_ID, text='Invalid message')['message_id']
            self.main_bot.remove_previous_messages(chat_ID)
            self.main_bot.update_message_to_remove(msg_id,chat_ID)
        userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
        old_start,old_end = self.main_bot.registry_interface.get_time_start_and_time_end_from_chatId(userid)
        if hour >= 0 and hour < 24 and minute >= 0 and minute <= 59:
            if checkp == 'start':
                time_start=mex
                time_end = old_end
            if checkp == 'end':
                time_end=mex
                time_start = old_start
        print(f'stopped listening for time for {chat_ID}')

        state = "auto"
        init = time_start
        end =  time_end
        body = {"plantCode":plantcode,'state':state,'init':init,'end':end}
        out = self.main_bot.registry_interface.update_interval(body)
        self.main_bot.set_uservariables_chatstatus(chat_ID,'start')
        if self.main_bot.manage_invalid_request(chat_ID,out):
            pass
        else:
            msg_id = self.main_bot.bot.sendMessage(chat_ID, text=f"start time {time_start}\nend time {time_end}")['message_id']
            self.main_bot.remove_previous_messages(chat_ID)
            self.main_bot.update_message_to_remove(msg_id,chat_ID)
        self.main_bot.manage_plant(chat_ID,plantcode)


    def led_switch(self,chat_ID,plantcode,percentage,m_mode_duration):                     # Switch remotely the led on and off
        # Once all variables perc and end of the duration sends it to the light_shift microservice
        userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
        plantcode
        state = "manual"
        init = time.time()
        body = {"plantCode":plantcode,'state':state,'init':init,'end':m_mode_duration}

        output = self.main_bot.registry_interface.update_interval(body)
        self.main_bot.manage_invalid_request(chat_ID,output)
        mex_mqtt =  { 'bn': "manual_light_shift",'e': [{ "n": "percentage_of_light", "u": "percentage", "t": time.time(), "v":float(percentage) },{"n": "init_hour", "u": "s", "t": time.time(), "v":init },{"n": "final_hour", "u": "s", "t": time.time(), "v": m_mode_duration } ]}
        self.main_bot.paho_mqtt.publish(f'RootyPy/{userid}/{plantcode}/lux_to_give/manual',json.dumps(mex_mqtt),2)
        time.sleep(2)
        self.main_bot.manage_plant(chat_ID,plantcode)

  
    def instant_switch_off(self,chat_ID,plantcode):                     # Switch remotely the led on and off
        # Short path to switch of the light by sending an mqtt message to light shift
        userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
        print('Light switched off manually')
        state = "manual"
        init = time.time()
        end = time.time()+10
        body = {"plantCode":plantcode,'state':state,'init':init,'end':end}
        output = self.main_bot.registry_interface.update_interval(body)
        self.main_bot.manage_invalid_request(chat_ID,output)
        mex_mqtt =  { 'bn': "manual_light_shift",'e': [{ "n": "percentage_of_light", "u": "percentage", "t": time.time(), "v":0.0 },{"n": "init_hour", "u": "s", "t": time.time(), "v":time.time()} ,{"n": "final_hour", "u": "s", "t": time.time(), "v":end} ]}
        self.main_bot.paho_mqtt.publish(f'RootyPy/{userid}/{plantcode}/lux_to_give/manual',json.dumps(mex_mqtt),2)
        print(f'SENT MESSAGE to RootyPy/{userid}/{plantcode}/lux_to_give/manual')
        self.main_bot.manage_plant(chat_ID,plantcode)


#--------------------------------------------------------- Plant watering --------------------------------------------------------------

class Irrigation_manager():

    def __init__(self,main_bot):
        self.main_bot = main_bot

    def water_plant(self, chat_ID,plantcode):                 
        # Activates the watering of the plant
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text="You chose to water the plant\nsend a percentange of the tank between 0 and 10")['message_id']
        self.main_bot.set_uservariables_chatstatus(chat_ID,f'listeningforwaterpercentage&{plantcode}')
        self.main_bot.remove_previous_messages(chat_ID)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)

    def eval_water_percentage(self,chat_ID,message):
        # Checks if the amount of water written is between 0 and 10
        message = message.strip()
        #try:
        perc_value = float(message)
        if perc_value <= 10 and perc_value > 0:
            plantcode = self.main_bot.get_uservariables_chatstatus(chat_ID).split('&')[1]
            models = self.main_bot.registry_interface.get_models()
            for model in models:
                if model["model_code"] == plantcode[0:2]:
                    tank_max = model["tank_capacity"]

            water_volume = tank_max*perc_value/100
            self.main_bot.set_uservariables_chatstatus(chat_ID,'start')
            msg_id = self.main_bot.bot.sendMessage(chat_ID,f'{perc_value} is a valid value')['message_id']
            self.main_bot.remove_previous_messages(chat_ID)
            self.main_bot.update_message_to_remove(msg_id,chat_ID)
            userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
            payload =  {"bn": f'{'Pump'}',"e":[{ "n": f"{self.main_bot.ClientID}", "u": "l", "t": time.time(), "v":water_volume }]}
            self.main_bot.paho_mqtt.publish(f'RootyPy/{userid}/{plantcode}/water_to_give/manual',json.dumps(payload),2)
            self.main_bot.manage_plant(chat_ID,plantcode)           
        else:
            msg_id = self.main_bot.bot.sendMessage(chat_ID,f'{perc_value} is a invalid value, senda a value between 0 and 10')['message_id']
            self.main_bot.update_message_to_remove(msg_id,chat_ID)
        #except:
        #    msg_id = self.main_bot.bot.sendMessage(chat_ID,f'{message} is an invalid value,try again')['message_id']
        #    self.main_bot.update_message_to_remove(msg_id,chat_ID)
        

# ------------------------------------------------- Report -------------------------------------------------------
class Report_manager():

    def __init__(self,report_url,main_bot,num_attempts):

        self.report_url = report_url
        self.main_bot = main_bot
        self.num_rest_attempts = num_attempts

    def set_report_generator_url(self,url):
        self.report_url = url

    def generate_instant_report(self,chat_ID,plantcode):
        # Get request for a report
        print(f'{chat_ID} is asking for a report')

        r = self.get_response(self.report_url+f'/getreport/{plantcode}')
        output = json.loads(r.text)
            # Extract the base64-encoded image and decode it
        image_base64 = output["e"][0]["v"]
        image_data = base64.b64decode(image_base64)

        
        # Extract the message
        message = output["e"][1]["v"]

        # Load the image into a BytesIO stream
        image = Image.open(BytesIO(image_data))
        bio = BytesIO()
        image.save(bio, format='PNG')
        bio.seek(0)

            # Send the image using the bot
        msg_id = self.main_bot.bot.sendPhoto(chat_ID, bio, caption=message)
        self.main_bot.update_message_to_remove(msg_id,chat_ID)
        self.main_bot.choose_plant(chat_ID)

    def set_report_frequency(self,chat_ID,plantcode):
        #Changes the report frequency for a plant
        userid = self.main_bot.registry_interface.get_username_for_chat_ID(chat_ID)
        output = self.main_bot.registry_interface.get_plants()
        for plant in output:
            if plant['userId'] == userid:
                oldsetting = plant['report_frequency']
                plantid = plant['plantId']
        self.main_bot.remove_previous_messages(chat_ID)

        msg_id = self.main_bot.bot.sendMessage(chat_ID,text = f'actual report frequency for {plantid} is {oldsetting}')['message_id']

        self.main_bot.update_message_to_remove(msg_id,chat_ID)
        buttons = [[InlineKeyboardButton(text=f'daily', callback_data=f'f_settings&daily&{plantcode}'), InlineKeyboardButton(text=f'weekly', callback_data=f'f_settings&weekly&{plantcode}'), InlineKeyboardButton(text='biweekly', callback_data=f'f_settings&biweekly&{plantcode}'),InlineKeyboardButton(text=f'monthly', callback_data=f'f_settings&monthly&{plantcode}')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text=f'when do you want to receive a report for {plantcode}', reply_markup=keyboard)['message_id']
        self.main_bot.update_message_to_remove(msg_id,chat_ID)


    def set_frequency_or_generate(self,chat_ID,plantcode):
        # Makes the user choose to generate areport or change settings
        buttons = [[ InlineKeyboardButton(text=f'generate report', callback_data=f'report&generate&{plantcode}'), InlineKeyboardButton(text=f'settings', callback_data=f'report&settings&{plantcode}'), InlineKeyboardButton(text=f'🔙', callback_data=f'plant&back&{plantcode}')]]
        keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
        msg_id = self.main_bot.bot.sendMessage(chat_ID, text='What do you want to do?', reply_markup=keyboard)['message_id']
        self.main_bot.update_message_to_remove(msg_id,chat_ID) 

    def get_response(self,url):
        # Tries a number of times a get request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None     
    
    def put_response(self,url,body):
        # Tries a number of times a put request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.put(url,json = body)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

class Registry_interface():

    def __init__(self,registry_url,num_rest_attempts,main_bot):
        self.registry_url = registry_url
        self.num_rest_attempts = num_rest_attempts
        self.main_bot = main_bot

    def get_users(self):
        r = self.get_response(self.registry_url+'/users')
        print(f'GET request sent at {self.registry_url}/users')
        output = json.loads(r.text)
        return output
    
    def update_interval(self,body):
        r = self.put_response(self.registry_url+'/updateInterval',body)
        out = json.loads(r.text)
        return out 
    
    def update_report_frequency(self,body):
        r = self.put_response(self.registry_url+'/setreportfrequency',body)
        return r
    
    def get_plants(self):
        r = self.get_response(self.registry_url+'/plants')
        print(f'GET request sent at {self.registry_url}/plants')
        output = json.loads(r.text)
        return output

    
    def set_new_report_frequency(self,chat_ID,newfrequency,plantcode):
        # Updates the catalog with the new frequency
        body = {'plantCode':plantcode,'report_frequency':newfrequency}
        r = self.main_bot.registry_interface.update_report_frequency(body)
        flag_keep_mex = self.main_bot.manage_invalid_request(chat_ID,json.loads(r.text))
        self.main_bot.choose_plant(chat_ID,flag_keep_mex)


    def get_plant_for_chatID(self, chatID):
        # gets the plant names for the user
        plant_list = []     
        userid = self.get_username_for_chat_ID(chatID)
        output =self.get_plants()
        for diz in output:
            if diz['userId'] == userid:
                plant_list.append(diz['plantId'])
        
        return plant_list
        
    def get_username_for_chat_ID(self,chat_ID):
        # Given the chat_ID returns the associated userId
        output = self.get_users()
        for diz in output:

            if diz['chatID'] == chat_ID:

                usern =diz['userId']
        
        return usern
    
    def get_available_plant_types(self):
        # Gets the list of available plant types
        r = self.get_response(self.registry_url+'/valid_plant_types')
        output = json.loads(r.text)
        plant_types =[]
        for diz in output:
            plant_types.append(diz['type'])
        return plant_types


    def get_plant_code_from_plant_name(self,userid,plantname):
        # Gets the plant code from the plant name written by the user 
        output = self.get_plants()
        for diz in output:
            if diz['userId'] == userid and diz['plantId'] == plantname:
                return diz['plantCode']
            
    def get_plantname_for_plantcode(self,plantcode):
        # Gets the plantname chosen by the user from the plantcode
        output = self.get_plants()
        for diz in output:

            if diz['plantCode'] == plantcode:

                plantname = diz['plantId']

        return plantname

    def get_services(self):
        r = self.get_response(self.registry_url+'/services')
        output = json.loads(r.text)
        return output

    def is_new_user(self,chat_ID):                   # Checks if the messaging chatID is between the registered chatID
        flag_user_present = 0       
        output = self.get_users()        
        for diz in output:
            if diz['chatID'] == None:
                pass
            elif int(diz['chatID']) == chat_ID:
                flag_user_present=1
        if flag_user_present == 1:
            return False
        else:
            return True  
        
    def get_chatID_for_username(self,userid):
        # Gets the chad_ID associated to a username
        output = self.get_users()
        for diz in output:

            if diz['userId'] == userid:

                chatid =diz['chatID']

        return chatid

    def get_response(self,url):
        # Tries a number of times a get request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

    def put_response(self,url,body):
        # Tries a number of times a put request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.put(url,json = body)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

    def post_response(self,url,body):
        # Tries a number of times a post request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.post(url,json = body)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

    def get_time_start_and_time_end_from_chatId(self,userid):
        # Asks the previous values of the auto mode
        output = self.get_plants()
        for plant in output:
            if plant['userId'] == userid:
                time_start = plant['auto_init']
                time_end = plant['auto_end']
        return time_start, time_end
    
    def get_models(self):
        r =self.get_response(self.registry_url+'/models')
        models = json.loads(r.text)
        return models
    
class Adaptor_interface():
    def __init__(self,adaptor_url,num_rest_attempts):
        self.adaptor_url = adaptor_url
        self.num_rest_attempts = num_rest_attempts
    
    def get_data(self,userid,plantcode,measurement,duration):
        duration = str(duration)
        r = self.get_response(f'{self.adaptor_url}/getData/{userid}/{plantcode}?measurament={measurement}&duration={duration}')
        return r
    
    def get_response(self,url):
        # Tries a number of times a get request untill an accetable result is returned
        for i in range(self.num_rest_attempts):
            try:
                response = requests.get(url)
                response.raise_for_status()
                return response
            except HTTPError as http_err:
                print(f"HTTP error occurred: {http_err}")
            except Exception as err:
                print(f"Other error occurred: {err}")
        return None

class Iamalive():
    #Object that takes care of sending periodics messages to the service registry 

    def __init__(self ,topic,update_time,id,port,broker,registry_interface):

        # mqtt attributes
        self.clientID = id
        self.port = port
        self.broker = broker
        self.pub_topic =topic
        self.paho_mqtt = pahoMQTT.Client(self.clientID,True)
        self.paho_mqtt.on_connect = self.myconnect_live
        self.message = {"bn": "updateCatalogService","e":[{ "n": f"{id}", "u": "", "t": time.time(), "v":f"{id}" }]}   # Message that the registry is going to receive
        self.starting_time = time.time()                         # this variable is gonna be updated to check and send the message
        self.interval = update_time
        self.registry_interface = registry_interface
        print('i am alive initialized')
        self.start_mqtt()

    def ask_for_urls(self,needed_urls):

        while '' in needed_urls.values():

            services = self.registry_interface.get_services()
            print(needed_urls)
            for service in services:
                if service['serviceID'] in needed_urls.keys():
                    needed_urls[service['serviceID']] = service['route']

        return needed_urls

    def start_mqtt(self):
        # Connects to broker and starts the mqtt
        print('>starting i am alive')
        self.paho_mqtt.connect(self.broker,self.port)
        self.paho_mqtt.loop_start()

    def myconnect_live(self,paho_mqtt, userdata, flags, rc):
       # Feedback on the connection
       print(f"telegrambot: Connected to {self.broker} with result code {rc}")

    def check_and_publish(self):
        # Updates the time value of the message
        actual_time = time.time()
        if actual_time > self.starting_time + self.interval:
            self.message["e"][0]["t"]= time.time()
            self.publish()
            self.starting_time = actual_time

    def publish(self):
        # Publishes the mqtt message in the right fromat
        __message=json.dumps(self.message)
        self.paho_mqtt.publish(topic=self.pub_topic,payload=__message,qos=2)
#--------------------------------------------------Subscrier----------------------------------

class Subscriber_telegram_bot():
    # Receives messages through MQTT, puts them in a message queue and handles them
    def __init__(self,id,port,broker,bot,sub_topics):
        print('initialiting subscriber')
        self.clientID = id
        self.port = port
        self.broker = broker
        self.message_queue = []                  #MQTT messages are stored here
        self.bot = bot                           # telegram bot
        self.paho_mqtt = pahoMQTT.Client(self.clientID,True) 
        self.topics = sub_topics    
        self.paho_mqtt.on_connect = self.myconnect_live
        self.paho_mqtt.on_message = self.on_message      
        self.start_mqtt()


    def start_mqtt(self):
        self.paho_mqtt.connect(self.broker,self.port)
        self.paho_mqtt.loop_start()
        for topic in self.topics:
            self.paho_mqtt.subscribe(topic,qos = 2)             #subscribes to the topics of interest
        print('subscribed to all topic')


    def myconnect_live(self,paho_mqtt, userdata, flags, rc):
       # notifies at connection completed
       print(f"telegrambot: Connected to {self.broker} with result code {rc}")

    def on_message(self, client, userdata, msg):
        # Reacts to an incoming message and stores it in the queue
        print(msg.topic)
        print(msg.payload)
        print(f"Received message on topic {msg.topic}")
        self.message_queue.append(msg)
    

    def empty_queue(self):
        # Empties the queue by directing the right method for the right topic
        for msg in self.message_queue:
            if 'RootyPy/WaterTankAlert/' in msg.topic:
                self.bot.Handle_water_tank_alert(msg)
            elif 'RootyPy/report_generator/' in msg.topic:
                self.bot.Handle_report(msg)
        self.message_queue = []
#-------------------------------------------------- Disconnect silent users -------------------------
class Active_user_checker():
    #Each user has a timer, this object updates the timer and, if the user timer reaches zero uses the bot to delete
    #the user fro mactive user checker
    def __init__(self,interval):

        #self.diz = diz
        self.interval = interval

    # Decrement the timer for each user in the chatstatus dictionary by the given interval.
    # Remove the user's status if the timer reaches or passes 0.
    def updating_user_timer(self,diz,bot):

        keys_to_remove = []
        for key in diz.keys():
            diz[key]['timer'] = diz[key]['timer'] - self.interval  # Decrement the timer by the interval
            if diz[key]['timer'] <= 0:
                # If the timer reaches or passes 0, remove the user's status
                keys_to_remove.append(key)
        for key in keys_to_remove:
            self.delete_user_status(diz,key,bot)
        return diz

    # Remove the status of a user identified by chat_ID from the chatstatus dictionary.
    def delete_user_status(self,diz, chat_ID,bot):
        bot.remove_previous_messages(chat_ID)
        del diz[chat_ID]  # Remove the entry for the user from the chatstatus dictionary
        print(f'{chat_ID} disconnected ')


if __name__ == "__main__":

    

    #config_bot = "C:\\Users\\Lenovo\\rootyPiCompose\\rootyPi\\telegram_bot\\telegram_bot_config.json"
    config_bot = "telegram_bot_config.json"
    sb=GreenHouseBot(config_bot)
