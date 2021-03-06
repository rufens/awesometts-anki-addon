from urllib.error import HTTPError
from warnings import warn

import tools.anki_testing
import tools.speech_recognition
import pytest
from pytest import raises
import magic # to verify file types
import os
import sys
import time

class Success(Exception):
    pass


def get_default_options(addon, svc_id):
    available_options = addon.router.get_options(svc_id)

    options = {}

    for option in available_options:
        key = option['key']
        if 'test_default' in option:
            value = option['test_default']
        elif 'default' in option:
            value = option['default']
        else:
            value = option['values'][0]
            if isinstance(value, tuple):
                value = value[0]
        options[key] = value

    return options

def clear_cache(cache_path):
    for filename in os.listdir(cache_path):
        file_path = os.path.join(cache_path, filename)
        os.unlink(file_path)

class TestClass():

    def setup_class(self):
        os.environ['AWESOMETTS_DEBUG_LOGGING'] = 'enable'
        self.anki_app = tools.anki_testing.get_anki_app()
        from awesometts import addon
        self.addon = addon
        self.logger = addon.logger
        # clear cache
        self.logger.debug(f'clearing cache: {self.addon.paths.cache}')        
        clear_cache(self.addon.paths.cache)

    def teardown_class(self):
        tools.anki_testing.destroy_anki_app()
        # clear cache
        self.logger.debug(f'clearing cache: {self.addon.paths.cache}')        
        clear_cache(self.addon.paths.cache)



    def test_addon_initialization(self):
        import awesometts
        awesometts.browser_menus()     # mass generator and MP3 stripper
        awesometts.cache_control()     # automatically clear the media cache regularly
        awesometts.cards_button()      # on-the-fly templater helper in card view
        awesometts.config_menu()       # provides access to configuration dialog
        awesometts.editor_button()     # single audio clip generator button
        awesometts.reviewer_hooks()    # on-the-fly playback/shortcuts, context menus
        awesometts.sound_tag_delays()  # delayed playing of stored [sound]s in review
        awesometts.temp_files()        # remove temporary files upon session exit
        awesometts.window_shortcuts()  # enable/update shortcuts for add-on windows
        # if we didn't hit any exceptions at this point, declare success
        assert True


    def test_gui(self):
        pass


    def test_services(self):
        # python -m pytest tests -rPP -k 'test_services'
        """Tests all services (except services which require an API key) using a single word.

        Retrieving, processing, and playing of word "successful" will be tested,
        using default (or first available) options. To expose a specific
        value of an option for testing purposes only, use test_default.
        """
        require_key = ['Baidu', 'iSpeech', 'Google Cloud Text-to-Speech', 'Microsoft Azure', 'Forvo', 'FptAi Vietnamese', 'Naver Clova', 'Naver Clova Premium']
        # in an attempt to get continuous integration running again, a number of services had to be disabled. 
        # we'll have to revisit this when we get a baseline of working tests

        # remove google translate, the quality is so low that it fails the recognition test
        # remove Oddcast, the low quality doesn't pass the recognition test, and we have a separate odcast test
        it_fails = ['Baidu Translate', 
                    'Duden', 
                    'abair.ie', 
                    'Fluency.nl',  
                    'ImTranslator', 
                    'NeoSpeech', 
                     'VoiceText', 
                     'Wiktionary', 
                     'Yandex.Translate', 
                     'NAVER Translate', 
                     'Google Translate',
                     'Oddcast', 
                     'Howjsay']

        for svc_id, name, in self.addon.router.get_services():

            if name in require_key:
                warn(f'Skipping {name} (no API key)')
                continue

            if name in it_fails:
                warn(f'Skipping {name} - known to fail; if you can fix it, please open a PR')
                continue

            self.logger.info(f'Testing service {name}')

            # some services only support a single word. so use a single word as input as a common denominator
            input_word = 'pronunciation'

            options = get_default_options(self.addon, svc_id)

            expected_language = 'en-US'

            with raises(Success):
                self.addon.router(
                    svc_id=svc_id,
                    text=input_word,
                    options=options,
                    callbacks={
                        'okay': self.get_verify_audio_callback(svc_id, options['voice'], input_word, expected_language, True, False),
                        'fail': self.get_failure_callback(svc_id, options['voice'], input_word, expected_language)
                    },
                    async_variable=False
                )

    def common_logger_prefix(self, svc_id, voice, expected_text, language):
        return f'Service {svc_id} voice=[{voice}] text_input=[{expected_text}] language=[{language}]'

    def get_verify_audio_callback(self, svc_id, voice, expected_text, language, lowercase, disable_recognition):
        """
        Build and return a callback which compares the received audio against the expected text, in the specified language
        """

        def verify_audio_text(path):
            logger_prefix = self.common_logger_prefix(svc_id, voice, expected_text, language)
            # make sure file exists
            self.logger.debug(f'{logger_prefix} retrieved audio file {path}, verifying that it exists')
            assert os.path.exists(path)
            # get filetype by looking at file header
            filetype = magic.from_file(path)
            # should be an MP3 file
            expected_filetype = 'MPEG ADTS, layer III'
            self.logger.debug(f'{logger_prefix} verifying that filetype contains [{expected_filetype}]')
            assert expected_filetype in filetype

            self.logger.debug(f'{logger_prefix} audio file {path} passed initial checks')

            # run this file through azure speech recognition
            if tools.speech_recognition.recognition_available() and not disable_recognition:
                self.logger.debug(f'{logger_prefix} speech recognition available')
                result_text = tools.speech_recognition.recognize_speech(path, language)
                self.logger.debug(f'{logger_prefix} detected text [{result_text}]')
                
                # make sure it's what we expect
                # need to lowercase ?
                if lowercase:
                    result_text = result_text.lower()

                # remove final ., 。 (for chinese) and lowercase
                result_text = result_text.replace('.', '').replace('。', '').replace('?', '')
                assert result_text == expected_text
                # at this point, declare success
                self.logger.debug(f'{logger_prefix} test success')
                raise Success()
            else:
                # we know we have an mp3 audio file, desclare success
                self.logger.debug(f'{logger_prefix} speech recognition not available, declare test successful')
                raise Success()
        return verify_audio_text

    def get_failure_callback(self, svc_id, voice, expected_text, language):
        logger_prefix = self.common_logger_prefix(svc_id, voice, expected_text, language)

        def failure(exception, text):
            self.logger.error(f'{logger_prefix} got exception: {exception} input_text: [{text}]')
            assert False
        return failure

    def run_service_testcases(self, svc_id, test_cases, extra_option_keys=[], lowercase=True, disable_recognition=False):
        """
        a generic way to run a number of test cases for a given service
        """

        self.logger.info(f'Testing service {svc_id} with {len(test_cases)} test cases')

        # get default options
        options = get_default_options(self.addon, svc_id)
        self.logger.info(f'Default options for service {svc_id}: {options}')

        for test_case in test_cases:
            # time.sleep(3) # used this to test azure token refresh code
            options['voice'] = test_case['voice']
            # set extra option keys
            for extra_option_key in extra_option_keys:
                if extra_option_key in test_case:
                    options[extra_option_key] = test_case[extra_option_key]
            text_input = test_case['text_input']
            expected_output = text_input
            if 'expected_output' in test_case:
                expected_output = test_case['expected_output']
            self.logger.info(f"Testing service {svc_id} with voice={options['voice']} and text_input={text_input}")
            with raises(Success):
                self.addon.router(
                    svc_id=svc_id,
                    text=text_input,
                    options=options,
                    callbacks={
                        'okay': self.get_verify_audio_callback(svc_id, options['voice'], expected_output, test_case['recognition_language'], lowercase, disable_recognition),
                        'fail': self.get_failure_callback(svc_id, options['voice'], text_input, test_case['recognition_language'])
                    },
                    async_variable=False
                )

    def test_google_cloud_tts(self):
        # test google cloud text-to-speech service
        # to run this test only:
        # python -m pytest tests -k 'test_google_cloud_tts'
        # requires an API key , which should be set on the travis CI build

        GOOGLE_CLOUD_TTS_KEY_ENVVAR = 'GOOGLE_SERVICES_KEY'
        if GOOGLE_CLOUD_TTS_KEY_ENVVAR not in os.environ:
            return

        service_key = os.environ[GOOGLE_CLOUD_TTS_KEY_ENVVAR]
        assert len(service_key) > 0

        svc_id = 'GoogleTTS'

        # add the google services API key in the config
        config_snippet = {
            'extras': {'googletts': {'key': service_key}}
        }
        self.addon.config.update(config_snippet)

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'en-US-Wavenet-D', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'en-GB-Standard-B', 'text_input': 'i want to save my stomach for veggie dumplings', 'recognition_language':'en-GB'},
            {'voice': 'fr-FR-Wavenet-B', 'text_input': 'ravi de vous rencontrer', 'recognition_language':'fr-FR'},
            {'voice': 'cmn-CN-Wavenet-B', 'text_input': '我试着每天都不去吃快餐', 'recognition_language':'zh-CN'},
        ]

        self.run_service_testcases(svc_id, test_cases)

    def test_azure(self):
        # test azure cognitive services API
        # to run this test only:
        # python -m pytest tests -rPP -k 'test_azure'
        # requires an API key , which should be set on the travis CI build

        AZURE_SERVICES_KEY_ENVVAR_NAME = 'AZURE_SERVICES_KEY'
        if AZURE_SERVICES_KEY_ENVVAR_NAME not in os.environ:
            return

        service_key = os.environ[AZURE_SERVICES_KEY_ENVVAR_NAME]
        assert len(service_key) > 0

        svc_id = 'Azure'

        # add the google services API key in the config
        config_snippet = {
            'extras': {'azure': {'key': service_key}}
        }
        self.addon.config.update(config_snippet)

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'Microsoft Server Speech Text to Speech Voice (en-US, BenjaminRUS)', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'Microsoft Server Speech Text to Speech Voice (fr-CH, Guillaume)', 'text_input': 'ravi de vous rencontrer', 'recognition_language':'fr-FR'},
            {'voice': 'Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)', 'text_input': '我试着每天都不去吃快餐', 'recognition_language':'zh-CN'},
        ]

        self.run_service_testcases(svc_id, test_cases)        


    @pytest.mark.skip(reason="2020/08/04 Naver is broken https://github.com/AwesomeTTS/awesometts-anki-addon/issues/117")
    def test_naver(self):
        # test Naver Translate service
        # to run this test only:
        # python -m pytest tests -s -k 'test_naver'

        svc_id = 'Naver'

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'en', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'ko', 'text_input': '여보세요', 'recognition_language':'ko-KR'},
            #{'voice': 'zh', 'text_input': '你好', 'recognition_language':'zh-CN'}, #chinese voice doesn't seem to work
            {'voice': 'ja', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
        ]

        self.run_service_testcases(svc_id, test_cases)

    def test_naverclova(self):
        # test Naver Clova service
        # to run this test only:
        # python -m pytest tests -s -k 'test_naverclova'

        svc_id = 'Naver Clova'

        NAVERCLOVA_CLIENT_ID_ENVVAR = 'NAVERCLOVA_CLIENT_ID'
        NAVERCLOVA_CLIENT_SECRET_ENVVAR = 'NAVERCLOVA_CLIENT_SECRET'
        if NAVERCLOVA_CLIENT_ID_ENVVAR not in os.environ or NAVERCLOVA_CLIENT_SECRET_ENVVAR not in os.environ:
            return

        client_id = os.environ[NAVERCLOVA_CLIENT_ID_ENVVAR]
        client_secret = os.environ[NAVERCLOVA_CLIENT_SECRET_ENVVAR]
        assert len(client_id)
        assert len(client_secret)

        # add api keys
        config_snippet = {
            'extras': {'naverclova': 
                {'clientid': client_id,
                 'clientsecret': client_secret}
            }
        }
        self.addon.config.update(config_snippet)

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'mijin', 'text_input': '여보세요', 'recognition_language':'ko-KR'},
            {'voice': 'jinho', 'text_input': '여보세요', 'recognition_language':'ko-KR'},
            {'voice': 'clara', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'matt', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'shinji', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},            
            {'voice': 'meimei', 'text_input': '你好', 'recognition_language':'zh-CN'},
            {'voice': 'liangliang', 'text_input': '你好', 'recognition_language':'zh-CN'},
            {'voice': 'jose', 'text_input': 'muchas gracias', 'recognition_language':'es-ES'},
            {'voice': 'carmen', 'text_input': 'muchas gracias', 'recognition_language':'es-ES'},
        ]

        self.run_service_testcases(svc_id, test_cases, extra_option_keys=['clientid', 'clientsecret'])

    def test_naverclovapremium(self):
        # test Naver Clova Premium service
        # to run this test only:
        # python -m pytest tests -s -k 'test_naverclovapremium'

        svc_id = 'Naver Clova Premium'

        NAVERCLOVA_CLIENT_ID_ENVVAR = 'NAVERCLOVA_CLIENT_ID'
        NAVERCLOVA_CLIENT_SECRET_ENVVAR = 'NAVERCLOVA_CLIENT_SECRET'
        if NAVERCLOVA_CLIENT_ID_ENVVAR not in os.environ or NAVERCLOVA_CLIENT_SECRET_ENVVAR not in os.environ:
            return

        client_id = os.environ[NAVERCLOVA_CLIENT_ID_ENVVAR]
        client_secret = os.environ[NAVERCLOVA_CLIENT_SECRET_ENVVAR]
        assert len(client_id)
        assert len(client_secret)

        # add api keys
        config_snippet = {
            'extras': {'naverclovapremium': 
                {'clientid': client_id,
                 'clientsecret': client_secret}
            }
        }
        self.addon.config.update(config_snippet)

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'nara', 'text_input': '여보세요', 'recognition_language':'ko-KR'},
        ]

        self.run_service_testcases(svc_id, test_cases, extra_option_keys=['clientid', 'clientsecret'])

    def test_youdao(self):
        # python -m pytest tests -s -k 'test_youdao'

        svc_id = 'Youdao'

        # generate audio files for all these test cases, then run them through the speech recognition API to make sure the output is correct
        test_cases = [
            {'voice': 'en', 'text_input': 'this is the first sentence', 'recognition_language':'en-US'},
            {'voice': 'jp', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
        ]

        self.run_service_testcases(svc_id, test_cases)

    def test_oxford(self):
        # python -m pytest tests -s -k 'test_oxford'

        svc_id = 'Oxford'
        test_cases = [
            {'voice': 'en', 'text_input': 'successful', 'recognition_language':'en-US'},
        ]
        self.run_service_testcases(svc_id, test_cases)        

    def test_cambridge(self):
        # python -m pytest tests -s -k 'test_cambridge'
        svc_id = 'Cambridge'
        test_cases = [
            {'voice': 'en-GB', 'text_input': 'successful', 'recognition_language':'en-GB'},
            {'voice': 'en-US', 'text_input': 'congratulations', 'recognition_language':'en-US'},
        ]
        self.run_service_testcases(svc_id, test_cases)

    def test_collins(self):
        # python -m pytest tests -s -k 'test_collins'
        svc_id = 'Collins'
        test_cases = [
            {'voice': 'en', 'text_input': 'successful', 'recognition_language':'en-GB'},
            {'voice': 'fr', 'text_input': 'bonjour', 'recognition_language':'fr-FR'},
            #{'voice': 'de', 'text_input': 'entschuldigung', 'recognition_language':'de-DE'}, doesn't seem to work
            #{'voice': 'zh', 'text_input': '你好', 'recognition_language':'zh-CN'}, # doesn't seem to work
        ]
        self.run_service_testcases(svc_id, test_cases)


    def test_oddcast(self):
        # python -m pytest tests -s -k 'test_oddcast'
        svc_id = 'Oddcast'

        test_cases = [
            {'voice': 'en/steven', 'text_input': 'successful', 'recognition_language':'en-US'},
            # thai
            {'voice': 'th/narisa', 'text_input': 'กรุงเทพฯ', 'recognition_language':'th-TH'},
            {'voice': 'th/sarawut', 'text_input': 'กรุงเทพฯ', 'recognition_language':'th-TH'},
            {'voice': 'th/somsi', 'text_input': 'กรุงเทพฯ', 'recognition_language':'th-TH'},
            # japanese
            {'voice': 'ja/show', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/misaki', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/haruka', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/hikari', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/himari', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/kaito', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/kyoko', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/ryo', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/sayaka', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
            {'voice': 'ja/takeru', 'text_input': 'おはようございます', 'recognition_language':'ja-JP'},
        ]
        self.run_service_testcases(svc_id, test_cases)

    def test_yandex(self):
        # python -m pytest tests -s -k 'test_yandex'
        svc_id = 'Yandex'

        test_cases = [
            {'voice': 'en_GB', 'text_input': 'successful', 'recognition_language':'en-GB'},
            #{'voice': 'es_ES', 'text_input': 'gracias', 'recognition_language':'en-ES'}, # spanish is broken
        ]
        self.run_service_testcases(svc_id, test_cases)                                

    @pytest.mark.skip(reason="2020/08/28 too many timeouts on the website")
    def test_duden(self):
        # python -m pytest tests -rPP -k 'test_duden'
        svc_id = 'Duden'
        test_cases = [
            {'voice': 'de', 'text_input': 'Hund', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'der Hund', 'expected_output':'Hund', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'die Straße', 'expected_output':'Straße', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'das Kind', 'expected_output':'Kind', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'das Können', 'expected_output':'Können', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'Können, das', 'expected_output':'Können', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'Können, Das', 'expected_output':'Können', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'Größe', 'recognition_language':'de-DE'},
            {'voice': 'de', 'text_input': 'Glück', 'recognition_language':'de-DE'},
        ]
        self.run_service_testcases(svc_id, test_cases, [], False)

    def test_forvo(self):
        # python -m pytest tests -rPP -k 'test_forvo'
        svc_id = 'Forvo'

        FORVO_SERVICES_KEY_ENVVAR_NAME = 'FORVO_SERVICES_KEY'
        if FORVO_SERVICES_KEY_ENVVAR_NAME not in os.environ:
            return

        service_key = os.environ[FORVO_SERVICES_KEY_ENVVAR_NAME]
        assert len(service_key) > 0

        # add the the API key in the config
        config_snippet = {
            'extras': {'forvo': {'key': service_key}}
        }
        self.addon.config.update(config_snippet)

        # run successful test cases
        # =========================

        test_cases = [
            {'voice': 'en', 'text_input': 'successful', 'recognition_language':'en-US'}, # no country set
            {'voice': 'en', 'sex': 'f', 'text_input': 'greetings', 'recognition_language':'en-US'}, # set sex=female
            {'voice': 'en', 'text_input': 'greetings', 'recognition_language':'en-US'}, # set country=USA
            {'voice': 'zh', 'sex': 'f', 'text_input': '你好吗？', 'recognition_language':'zh-CN'}, # chinese, female
            {'voice': 'pt', 'sex': 'f', 'text_input': 'obrigado', 'recognition_language':'pt-PT'}, # portuguese, portugal, female
            {'voice': 'pt', 'sex': 'm', 'country':'BRA', 'text_input': 'obrigado', 'recognition_language':'pt-BR'}, # portuguese, brazil, male
        ]
        self.run_service_testcases(svc_id, test_cases, ['country', 'sex'])

        # run a few failure cases
        # =======================

        if False: # this seems to fail, do_spawn not defined in a failure case when async_variable=False
            # get default options
            options = get_default_options(self.addon, svc_id)
            self.logger.info(f'Default options for service {svc_id}: {options}')

            def error_case_success_callback(path):
                # shouldn't happen
                assert False

            def error_case_failure_callback(exception, text):
                self.logger.info(f'got failure {exception} for text={text}')
                if exception == 'Pronunciation not found in Forvo for word [unfortunately], language=fr sex=m, country=ANY':
                    raise Success()

            options['voice'] = 'fr'
            with raises(Success):
                self.addon.router(
                    svc_id=svc_id,
                    text='unfortunately', # this word shouldn't exist in french
                    options=options,
                    callbacks={
                        'okay': error_case_success_callback,
                        'fail': error_case_failure_callback
                    },
                    async_variable=False
                )

    def test_ftpai(self):
        # python -m pytest tests -rPP -k 'test_ftpai'
        svc_id = 'fptai'

        FPTAI_SERVICES_KEY_ENVVAR_NAME = 'FPTAPI_SERVICES_KEY'
        if FPTAI_SERVICES_KEY_ENVVAR_NAME not in os.environ:
            return

        service_key = os.environ[FPTAI_SERVICES_KEY_ENVVAR_NAME]
        assert len(service_key) > 0

        # add the the API key in the config
        config_snippet = {
            'extras': {'fptai': {'key': service_key}}
        }
        self.addon.config.update(config_snippet)

        # run successful test cases
        # =========================

        test_cases = [
            {'voice': 'leminh', 'text_input': 'Tôi không hiểu.', 'recognition_language': 'vi-VN'},
            {'voice': 'linhsan', 'text_input': 'Tôi không hiểu.', 'recognition_language': 'vi-VN'},
            {'voice': 'banmai', 'text_input': 'Tôi không hiểu.', 'recognition_language': 'vi-VN'},
            {'voice': 'banmai', 'text_input': 'Có thể giới thiệu cho tôi một khách sạn khác được không?', 'recognition_language': 'vi-VN'},
            {'voice': 'leminh', 'text_input': 'Có chấp nhận thẻ tín dụng không?', 'recognition_language': 'vi-VN'}
        ]
        # speech recognition not available for vietnamese
        self.run_service_testcases(svc_id, test_cases, [], False, True)