import logging
import random
import time
from typing import Callable, Dict, Iterable, Optional, Union
import json
import okx.Funding as Funding
import okx.SubAccount as SubAccount
import requests
from eth_abi import encode
from eth_account import Account
from eth_account.messages import defunct_hash_message
from requests import Session
from requests.auth import HTTPProxyAuth
from web3 import Web3
from web3.middleware import geth_poa_middleware


def read_wallets_from_file(filename):
    with open (filename, 'r') as file:
        lines = [line.strip() for line in file.readlines()]
    return lines

def read_proxies_from_file(filename):
    with open (filename, 'r') as file:
        lines = file.readlines()
    
    i = 0
    data_dict = {}
    for line in lines:
        parts = line.strip().split(':')
        if len(parts) == 4:
            ip, port, login, password = parts
            data_dict[i] = {
                'ip': ip,
                'port': port,
                'login': login,
                'password': password,
                'callable': True
            }
        else:
            print(f'Некорректная строка: {line}')
        i+=1
    
    return data_dict

def wait_balance_change_decorate(get_balance: Callable, main_function: Callable, get_balance_args: tuple = (), main_function_args: tuple = (), main_function_kwargs: dict = {}) -> Union[None, any]:
    # Получаем стартовый баланс
    old_balance = get_balance(*get_balance_args)

    # Выполняем основную функцию
    result = main_function(*main_function_args, **main_function_kwargs)

    # Ждем, пока баланс не изменится
    while old_balance == get_balance(*get_balance_args):
        time.sleep(10)

    return result


#TODO: make try except clear code
class CryptoWallet:
    '''
    web3 cryptoaccount 
    '''
    def __init__(self, private_key: str,chain_data: Dict, proxies:Iterable = None) -> None:
        self.private_key = private_key
        self.proxies = proxies
        # chain_data =
        # {'ethereum'      : {'rpc': 'https://rpc.ankr.com/eth', 'scan': 'https://etherscan.io/tx', 'token': 'ETH', 'chain_id': 1}}
        self.chain_data = chain_data

        # Настройка логгера
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)  # Установите уровень логгирования по вашему выбору.

        # Создание обработчика консольного вывода
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)  # Установите уровень логгирования для консольного вывода.

        # Создание форматтера
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)

        # Добавление обработчика к логгеру
        self.logger.addHandler(console_handler)

    def _get_random_proxy(self) -> Optional[Dict]:
        '''
        Returns a proxy dict with keys: ip, port, login, password
        '''
        try:
            if self.proxies:
                return random.choice(self.proxies)
            else:
                return None
        except Exception as e:
            self.logger.error(f'Error in getting proxy: {e}', exc_info=True)
            return None

    def get_address(self) -> str:
        '''
        get address from privatekey
        '''
        try:
            return Account.from_key(self.private_key).address
        except Exception as e:
            self.logger.error(f'Error in getting address: {e}', exc_info=True)
            return ''


    def get_balance_wei(self, chain:str) -> Optional[float]:
        '''
        get balance in wei (1 ETH / 10**18)
        '''
        try:
            w3 = self.get_w3_provider(chain) 
            balance_wei = w3.eth.get_balance(self.get_address())
            return balance_wei
        except Exception as e:
            self.logger.error(f'Error in getting balance: {e}', exc_info=True)
            return None

    
    def get_rpc(self, chain: str) -> Optional[str]:
        '''
        Get the RPC (Remote Procedure Call) for the specified blockchain.

        Parameters:
        - chain (str): The name of the blockchain.

        Returns:
        - str or None: The RPC URL for the specified blockchain, or None if not found.
        '''
        try:
            chain_data = self.chain_data.get(chain, {})
            return chain_data.get('rpc')
        except Exception as e:
            self.logger.error(f'Error in getting rpc: {e}', exc_info=True)
            return None


    def get_gas(self, chain:str) -> Optional[Dict]:
        try:
            web3 = self.get_w3_provider(chain)
            web3.middleware_onion.inject(geth_poa_middleware, layer=0)
            max_priority = web3.eth.max_priority_fee
            last_block = web3.eth.get_block('latest')
            base_fee = last_block['baseFeePerGas']
            block_filled = last_block['gasUsed'] / last_block['gasLimit'] * 100
            if block_filled > 50:
                base_fee *= 1.125
            max_fee = int(base_fee + max_priority)
            return {'maxPriorityFeePerGas': max_priority, 'maxFeePerGas': max_fee}
        except Exception as e:
            self.logger.error(f'Error in getting gas: {e}', exc_info=True)
            return None


    def get_w3_provider(self,chain:str) -> Optional[Web3]:
        try:
            proxy = self._get_random_proxy()
            if proxy:
                proxy_ip = proxy['ip']
                proxy_port = proxy['port']
                proxy_user = proxy['login']
                proxy_pass = proxy['password']
                proxy_string = f'http://{proxy_ip}:{proxy_port}'
                proxy_auth = HTTPProxyAuth(proxy_user, proxy_pass)

                

                session = Session()
                session.proxies = {
                    'http': proxy_string,
                    # 'https': proxy_string,
                }
                session.auth = proxy_auth  # Добавляем аутентификацию к сессии

                web3 = Web3(Web3.HTTPProvider(endpoint_uri=self.get_rpc(chain), session=session))
            else:
                
                web3 = Web3(Web3.HTTPProvider(self.get_rpc(chain)))
            
            return web3
        except Exception as e:
            self.logger.error(f'Error in get_w3_provider: {e}', exc_info=True)
            return None

    def get_contract_functions_from_abi(self,abi) -> dict:
        abi_json = json.loads(abi)
        contract_functions = [item['name'] for item in abi_json if item['type'] == 'function']
        return contract_functions
        

    # def make_contract_tx(self, function_name, *args, **transaction_params):
    #     # Получаем функцию контракта по имени
    #     contract_function = getattr(self.contract.functions, function_name)

    #     # Подготовка параметров для транзакции
    #     transaction_parameters = {
    #         'from': self.web3.eth.defaultAccount,
    #         'gas': transaction_params.get('gas', 200000),
    #         'gasPrice': transaction_params.get('gas_price', self.web3.eth.gas_price),
    #         'nonce': transaction_params.get('nonce', self.web3.eth.get_transaction_count(self.web3.eth.defaultAccount)),
    #     }
        
    #     return contract_function


    def make_tx(self, recipient: str, value: int, gas: int, chain: str) -> dict:
        '''
        Create a transaction without sending it.

        Returns:
        - dict: The created transaction.
        '''
        try:
            web3 = self.get_w3_provider(chain)

            value = int(value - gas * web3.eth.gas_price * 1.1 // 10 ** 12 * 10 ** 12)

            transaction = {
                'from': web3.to_checksum_address(self.get_address()),
                'to': web3.to_checksum_address(recipient),
                'chainId': web3.eth.chain_id,
                'nonce': web3.eth.get_transaction_count(web3.to_checksum_address(self.get_address())),
                'value': value,
                'gas': gas,
                **self.get_gas(chain),
            }

            transaction['gas'] = int(int(transaction['gas']) * 1.1)
            self.logger.info(f'Transaction details: {transaction}')
            return transaction

        except Exception as e:
            self.logger.error(f'Error in make_tx: {e}', exc_info=True)
            return {}
        
    def send_tx(self, transaction: dict, chain:str) -> None:
        '''
        Send a previously created transaction.

        Parameters:
        - transaction (dict): The transaction to be sent.

        Returns:
        - None
        '''
        try:
            web3 = self.get_w3_provider(chain)

            signed_transaction = web3.eth.account.sign_transaction(transaction, self.private_key)
            self.logger.info(f'Signed transaction: {signed_transaction}')


            # Отправка транзакции
            transaction_hash = web3.eth.send_raw_transaction(signed_transaction.rawTransaction)
            self.logger.info(f'Transaction Hash: {transaction_hash.hex()}')

        except Exception as e:
            self.logger.error(f'Error in send_tx: {e}', exc_info=True)



    def wait_balance_change(self, old_balance: Union[int, float], get_new_balance: Callable, interval: int = 10) -> None:
        '''
        Wait for the balance to change by periodically checking the new balance.

        Parameters:
        - old_balance (Union[int, float]): The old balance to compare.
        - get_new_balance (Callable): A callable function to get the new balance.
        - interval (int): The time interval in seconds between balance checks. Default is 10 seconds.

        Returns:
        - None
        '''
        while old_balance == get_new_balance():
            time.sleep(interval)
    

    



#TODO: make typisation make try except clear code
class OKX:
    def __init__(self, API_key:str, API_secret_key:str, passphrase:str):
        flag = '0'
        self.subAccountAPI = SubAccount.SubAccountAPI(API_key, API_secret_key, passphrase, False, flag)
        self.fundingAPI = Funding.FundingAPI(API_key, API_secret_key, passphrase, False, flag)
    
    def get_balances(self) -> Iterable: 
        try:
            return [{'ccy': i['ccy'], 'availBal':i['availBal']} for i in self.fundingAPI.get_balances()['data']]
        except Exception as e:
            print (f'Error while claiming balance')
            print (e)
            return None 


    def chain_withdrawal_from_okx(self, toAddr:str, amt:str, ccy:str='ETH', chain:str='ETH-Optimism') -> None:
        result = self.fundingAPI.get_currencies()
        min_fee = [str(item['minFee']) for item in result['data'] if item['ccy']=='ETH' and item['chain'] == chain][0]
        result = self.fundingAPI.withdrawal(
            ccy = ccy,
            toAddr = toAddr,
            amt = amt,
            fee = min_fee,
            dest = '4', 
            chain = chain
        )
        
        
    def get_subacc_eth_balance(self, name:str, ccy='ETH') -> str:
        try:
        
            data = [{'ccy': i['ccy'], 'availBal':i['availBal']} for i in self.subAccountAPI.get_funding_balance(subAcct=name)['data']]
            eth_bal = [i['availBal'] for i in data if i['ccy'] == ccy][0]
            return eth_bal
            
        except Exception as e:
            print (f'Error while claiming balance from subacc: {name} || {e}')
            return None

    def subacc_to_acc(self, subAcct:str, ccy='ETH') -> None:
        try:
            return self.fundingAPI.funds_transfer(
                type = 2,
                subAcct = subAcct,
                ccy = ccy,
                from_ = '6',
                to = '6',
                amt = self.get_subacc_eth_balance(subAcct)
            )
        except Exception as e:
            print (f'Error while sending money from subacc: {subAcct} || {e}')
            

    def get_all_subacc_balances(self,ccy='ETH'):
        subacc_data = self.subAccountAPI.get_subaccount_list()['data']
        result = []
        for subacc in subacc_data:
            name = subacc['subAcct']
            balance =self.get_subacc_eth_balance(name, ccy)
            result.append(balance)
        return result

    def move_all_from_subaccs_to_acc(self, ccy='ETH') -> None:
        '''
        move all ccy from subbaccs to main account 
        '''
        subacc_data = self.subAccountAPI.get_subaccount_list()['data']
        for subacc in subacc_data:
            name = subacc['subAcct']
            balance =self.get_subacc_eth_balance(name, ccy)
            if balance:
                self.subacc_to_acc(name, ccy)

    def wait_balance_change(self, old_balance: Union[int, float], get_new_balance: Callable, interval: int = 10) -> None:
        '''
        Wait for the balance to change by periodically checking the new balance.

        Parameters:
        - old_balance (Union[int, float]): The old balance to compare.
        - get_new_balance (Callable): A callable function to get the new balance.
        - interval (int): The time interval in seconds between balance checks. Default is 10 seconds.

        Returns:
        - None
        '''
        while old_balance == get_new_balance():
            time.sleep(interval)
