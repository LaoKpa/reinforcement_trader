import random
import json
import gym
from gym import spaces
import pandas as pd
import numpy as np


MAX_ACCOUNT_BALANCE = 2147483647
MAX_NUM_SHARES = 2147483647
MAX_SHARE_PRICE = 5000
MAX_OPEN_POSITIONS = 5
MAX_STEPS = 20000
COMMISSION_FEE = 0.008

INITIAL_ACCOUNT_BALANCE = 10000


class StockTradingEnv(gym.Env):
    # metadata = {'render.modes': ['human']}

    def __init__(self, df_list, isTraining=True):
        super(StockTradingEnv, self).__init__()

        self.training = isTraining
        self.window_size = 6
        self.df_list = []

        df_list[0].dropna(inplace = True)
        self.intersect_dates = df_list[0]['Date']
        for df in df_list[1:]:
            df.dropna(inplace = True)
            self.intersect_dates = np.intersect1d(self.intersect_dates, df['Date'])
        # Remove all NAN in the df
        
        self.start_date = np.min(self.intersect_dates)
        self.end_date = np.max(self.intersect_dates)

        for df in df_list:
            self.df_list.append(df[df['Date'].isin(self.intersect_dates)].reset_index(drop=True))

        # For Multiple Markets: Adding the CASH to the action
        self.market_number = len(df_list)+1
        lower_bond = [[0.0]*self.market_number]*3
        lower_bond = np.array(lower_bond)
        lower_bond = np.reshape(lower_bond, (1,-1))

        upper_bond = [[1.0]*self.market_number]*3
        upper_bond = np.array(upper_bond)
        upper_bond = np.reshape(upper_bond, (1,-1))

        self.action_space = spaces.Box(
            low=lower_bond[0], high=upper_bond[0], dtype=np.float16)
        # Lower bond: [[0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 0.0]]
        # Upper bond: [[3.0, 3.0, 3.0, 3.0], [1.0, 1.0, 1.0, 1.0], [1.0, 1.0, 1.0, 1.0]]

        # Prices contains the OHCL values for the last six prices
        self.observation_space = spaces.Box(
            low=0, high=1, shape=(self.market_number, 6, 6), dtype=np.float16)

    def _next_observation(self):
        '''
        The _next_observation method compiles the stock data for the last five time steps, 
        appends the agent’s account information, and scales all the values to between 0 and 1.
        '''

        # self.current_step is defined in reset method,
        # We assume the current_step is TODAY (BEFORE FINAL), which means we only know infomation till YESTERDAY ENDS.
        obs_list = []

        for i, df in enumerate(self.df_list):

            frame = np.array([
                df.loc[self.current_step-self.window_size: self.current_step - 1,
                       'Open'].values / MAX_SHARE_PRICE,

                df.loc[self.current_step-self.window_size: self.current_step - 1,
                       'High'].values / MAX_SHARE_PRICE,

                df.loc[self.current_step-self.window_size: self.current_step - 1,
                       'Low'].values / MAX_SHARE_PRICE,

                df.loc[self.current_step-self.window_size: self.current_step - 1,
                       'Price'].values / MAX_SHARE_PRICE,

                df.loc[self.current_step-self.window_size: self.current_step - 1,
                       'Vol'].values / MAX_NUM_SHARES,
            ], dtype=np.float64)

            # Append additional data and scale each value to between 0-1
            obs = np.append(frame, [[
                self.cash / INITIAL_ACCOUNT_BALANCE,
                self.total_net_worth / INITIAL_ACCOUNT_BALANCE,
                self.net_worth[i] / INITIAL_ACCOUNT_BALANCE,
                self.cost_basis[i] / INITIAL_ACCOUNT_BALANCE,
                self.total_sales_value[i] / MAX_NUM_SHARES,
                0.0
            ]], axis=0)

            obs_list.append(obs)

        cash_obs = np.array([
            np.array([1.0]*self.window_size) / MAX_SHARE_PRICE,
            np.array([1.0]*self.window_size) / MAX_SHARE_PRICE,
            np.array([1.0]*self.window_size) / MAX_SHARE_PRICE,
            np.array([1.0]*self.window_size) / MAX_SHARE_PRICE,
            np.array([1.0]*self.window_size)
        ], dtype=np.float64)

        cash_obs = np.stack(cash_obs)

        cash_obs = np.append(cash_obs, [[
            self.cash / INITIAL_ACCOUNT_BALANCE,
            self.total_net_worth / INITIAL_ACCOUNT_BALANCE,
            self.cash / INITIAL_ACCOUNT_BALANCE,
            1 / INITIAL_ACCOUNT_BALANCE,
            self.cash / MAX_NUM_SHARES,
            0.0
        ]], axis=0)

        obs_list.append(cash_obs)

        obs_array = np.array(obs_list)
        obs_array[pd.isna(obs_array)] = 0
        obs_array[np.isinf(obs_array)] = 1

        self.backup_obs = np.array(obs_list, dtype=np.float64)

        return self.backup_obs

    def _take_action(self, action):
        # Set the current price to a random price within the time step
        # dim(self.actual_price) = [n,6], dim(action) = [1, n+1]

        self.actual_price = np.array([random.uniform(df.loc[self.current_step, "Low"],
                                                     df.loc[self.current_step, "High"]) for df in self.df_list], dtype=np.float64)
        self.actual_price = np.append(self.actual_price, 1)
        # Add CASH price = 1, now dim=n+1
        self.actual_price[pd.isna(self.actual_price)] = self.prev_buyNhold_price[pd.isna(self.actual_price)]
        tradable_asset = (pd.isna(self.actual_price).astype(int))*(-1)+1

        action = np.reshape(action, (3,-1))

        action_type = np.floor(action[0]*2.99).astype(int)*tradable_asset
        self.current_action = action_type
        
        sell_percent = action[1] * (action_type == 1)
        
        buy_percent = action[2] * (action_type == 2)
        if np.nansum(buy_percent) > 1:
            buy_percent = buy_percent/np.nansum(buy_percent)
        

        '''
        Updated on 20 Feb.
        1. decision in [0,1], where [0,1] = Hold, [1,2] = Sell, [2,3] = Buy
        # Buy or sell is EITHER/OR, cannot happen concurrently
        2. sell_percent is the percentage of each inventory.
        3. Calculate the total cash from sell (including "selling cash", which means put the cash into the pool)
        4. Calculate the amount of cash used to purchase asset (including "buying cash")
        5. Calculate the number for buying
        6. Update the inventory
        '''

        # dim:n+1, those with no price will be nan
        
        
        inventory_value = self.actual_price * self.inventory_number
        
        sell_number = self.inventory_number * sell_percent
        sell_value = sell_number * self.actual_price
        inv_number_after_sell = self.inventory_number - sell_number

        cash_from_sale = np.sum(sell_value) * (1-COMMISSION_FEE)
        cash_from_sale += inventory_value[-1] * sell_percent[-1] * COMMISSION_FEE # NO commission fee for "selling" the CASH

        extra_cash_percent = 1-np.nansum(buy_percent)
        buy_value = cash_from_sale * buy_percent * (1-COMMISSION_FEE)
        buy_value[-1] += cash_from_sale * buy_percent[-1] * COMMISSION_FEE
        buy_value[-1] += cash_from_sale * extra_cash_percent
        buy_number = buy_value / self.actual_price

        
        self.total_sales_value += sell_value

        prev_cost = self.cost_basis * self.inventory_number
        self.inventory_number = inv_number_after_sell + buy_number
        
        if np.isnan(self.inventory_number).any():
            self.inventory_number = self.back_up_inv
        else:
            self.back_up_inv = self.inventory_number

        a = (prev_cost - sell_value + buy_value)
        b = self.inventory_number
        self.cost_basis = np.divide(a, b, out=np.zeros_like(a), where=b!=0)
        
        self.cost_basis[pd.isna(self.cost_basis)] = 0
        self.cost_basis[np.isinf(self.cost_basis)] = 0
        
        self.cash = self.inventory_number[-1]
        
        self.prev_net_worth = self.net_worth
        self.net_worth = self.inventory_number * self.actual_price
        
        self.prev_total_net_worth = self.total_net_worth
        self.total_net_worth = np.sum(self.net_worth)
        if self.total_net_worth > self.max_net_worth:
            self.max_net_worth = self.total_net_worth
        
        if np.isnan(self.inventory_number).any():
            raise Exception("Inv NAN WARNING!")

    '''
        action_type = action[0]
        buyAmount = action[1]
        sellAmount = action[2]

        if action_type < 1:
            # [0,1): Buy amount % of balance in shares
            cash_spend = self.balance * buyAmount
            if cash_spend < 0.01*self.net_worth:  # Not executing this transaction
                buyAmount = 0
                cash_spend = 0
                self.current_action = 0
            else:
                shares_bought = cash_spend / \
                    (self.actual_price*(1+COMMISSION_FEE))
                self.current_action = shares_bought
                prev_cost = self.cost_basis * self.shares_held

                self.balance -= cash_spend
                self.cost_basis = (
                    prev_cost + cash_spend) / (self.shares_held + shares_bought)
                self.shares_held += shares_bought

        elif action_type < 2:
            # [1,2): Sell amount % of shares held

            shares_sold = self.shares_held * sellAmount
            cash_get = shares_sold*self.actual_price*(1-COMMISSION_FEE)
            if cash_get < 0.001*self.net_worth:  # Not executing this transaction
                sellAmount = 0
                shares_sold = 0
                cash_get = 0
                self.current_action = 0
            else:
                self.current_action = shares_sold*-1
                self.balance += shares_sold * self.actual_price
                self.shares_held -= shares_sold
                self.total_shares_sold += shares_sold
                self.total_sales_value += shares_sold * self.actual_price
        else:  # [2,3): Hold
            self.current_action = 0

        self.prev_net_worth = self.net_worth
        self.net_worth = self.balance + self.shares_held * self.actual_price

        if self.net_worth > self.max_net_worth:
            self.max_net_worth = self.net_worth

        if self.shares_held == 0:
            self.cost_basis = 0
    '''

    def step(self, action):
        '''
        Next, our environment needs to be able to take a step. 
        At each step we will take the specified action (chosen by our model), 
        calculate the reward, and return the next observation.
        '''

        if np.isnan(action).any():
            action = np.nan_to_num(action)
                

        # 1. Determine TODAY's Date (For training)
        if self.current_step >= len(self.intersect_dates)-1:
            # if self.training:
            if self.training:
                self._take_action(action)
                self.current_step = self.window_size  # Going back to time 0
            else:  # if is testing
                if not self.finished:
                    self.finished = True
                    print("$$$$$$$$$$$ CASH OUT at time " +
                          str(self.intersect_dates[self.current_step-1]) + "$$$$$$$$$$$")
                    # SELL EVERYTHING on the last day
                    new_action = [1.0]*(self.market_number-1) + [2.0]
                    # First Row [1,1,1,...,2]

                    new_action += [1.0]*(self.market_number-1) + [0.0]
                    # Second Row [1,1,1,...,0]

                    new_action += [0.0]*(self.market_number-1) + [1.0]
                    # Third Row [0,0,0,...,1]
                    new_action = np.array(new_action)

                    self._take_action(new_action)
                    self.current_step += 1
                else:
                    self.finished_twice = True
        else:
            # 1. Execute TODAY's Action
            self._take_action(action)
            '''
            Updates self.balance, self.cost_basis, self.shares_held,
                    self.total_shares_sold, self.total_sales_value,
                    self.net_worth, self.max_net_worth, 
            '''
            self.current_step += 1
            # ****IMPORTANT: From now on, the current_step becomes TOMORROW****
            # Keep the current_step undiscovered

        '''
        We want to incentivize profit that is sustained over long periods of time. 
        At each step, we will set the reward to the account balance multiplied by 
        some fraction of the number of time steps so far.

        The purpose of this is to delay rewarding the agent too fast in the early stages 
        and allow it to explore sufficiently before optimizing a single strategy too deeply. 
        It will also reward agents that maintain a higher balance for longer, 
        rather than those who rapidly gain money using unsustainable strategies.
        '''

        close_prices = [df.loc[self.current_step-1, "Price"] for df in self.df_list]
        close_prices.append(1)
        close_prices = np.array(close_prices, dtype=np.float64)

        self.prev_buyNhold_balance = self.buyNhold_balance
        self.buyNhold_balance = np.sum(
            self.init_buyNhold_amount * close_prices)
        self.prev_buyNhold_price = close_prices

        profit = self.total_net_worth - INITIAL_ACCOUNT_BALANCE
        actual_profit = self.total_net_worth - self.buyNhold_balance

        # delay_modifier = (self.current_step / MAX_STEPS)
        # reward = self.balance * delay_modifier  # Original Version
        # reward = actual_profit * delay_modifier  # Use Actual Net Profit

        total_net_worth_delta = self.total_net_worth - self.prev_total_net_worth
        buyNhold_delta = self.buyNhold_balance - self.prev_buyNhold_balance

        reward = (total_net_worth_delta+1) / \
            (buyNhold_delta+1)  # TODO: NEED TO Reengineer!!!

        # OpenAI will reset if done==True
        done = (self.total_net_worth <= 0) or self.finished_twice

        if not self.finished:
            obs = self._next_observation()
        else:
            self.current_step -= 1
            obs = self._next_observation()
            self.current_step += 1

        if not self.finished_twice:
            info = {"profit": profit, "total_shares_sold": self.total_sales_value,
                    "actual_profit": actual_profit}
        else:
            info = {"profit": 0, "total_shares_sold": 0, "actual_profit": 0}
        return (obs, reward, done, info)

    def reset(self):
        # Reset the state of the environment to an initial state
        self.cash = INITIAL_ACCOUNT_BALANCE / self.market_number
        self.total_net_worth = INITIAL_ACCOUNT_BALANCE
        self.prev_total_net_worth = INITIAL_ACCOUNT_BALANCE
        self.max_net_worth = INITIAL_ACCOUNT_BALANCE
        self.current_step = 0

        self.prev_buyNhold_balance = 0
        self.finished = False
        self.finished_twice = False

        self.net_worth = np.array(
            [INITIAL_ACCOUNT_BALANCE / self.market_number] * self.market_number, 
            dtype=np.float64)

        
        
        self.total_sales_value = np.array([0.0] * self.market_number)
        self.prev_net_worth = self.net_worth

        self.current_action = np.array(
            [0.0]*self.market_number, dtype=np.float64)

        # Set the current step to a random point within the data frame
        # We set the current step to a random point within the data frame, because it essentially gives our agent’s more unique experiences from the same data set.
        if self.training:
            days_range = len(self.intersect_dates)
            rand_days = random.randint(self.window_size, days_range - 1)
            self.current_step = rand_days
        else:
            self.current_step = self.window_size

        init_price = [df.loc[0, "Price"] for df in self.df_list]
        init_price.append(1.0)
        init_price = np.array(init_price, dtype=np.float64)

        self.prev_buyNhold_price = init_price
        self.init_buyNhold_amount = (INITIAL_ACCOUNT_BALANCE/self.market_number) / init_price
        self.buyNhold_balance = INITIAL_ACCOUNT_BALANCE

        self.inventory_number = self.init_buyNhold_amount
        self.back_up_inv = self.inventory_number
        self.cost_basis = init_price



        return self._next_observation()

    def render(self, mode='human', close=False, afterStep=True):
        '''
        afterStep: if is rendered after the step function, the current_step should -=1.
        '''
        if afterStep:
            todayDate = self.intersect_dates[self.current_step-1]
        else:
            todayDate = self.intersect_dates[self.current_step]
        if mode == 'human':
            # Render the environment to the screen
            profit = self.total_net_worth - INITIAL_ACCOUNT_BALANCE

            print(f'Date: {todayDate}')
            print(f'Balance: {self.cash}')
            print(
                f'Shares held: {self.inventory_number}')
            print(
                f'Avg cost for held shares: {self.cost_basis} (Total sales value: {self.total_sales_value})')
            print(
                f'Net worth: {self.net_worth} (Total net worth: {self.total_net_worth})')
            print(f'Profit: {profit}')

        elif mode == 'detail':  # Want to add all transaction details
            net_worth_delta = self.total_net_worth - self.prev_total_net_worth
            buyNhold_delta = self.buyNhold_balance - self.prev_buyNhold_balance
            return {
                "date": todayDate,
                "actual_price": self.actual_price,
                "action": self.current_action,
                "inventory": self.net_worth,
                "shares_held": self.inventory_number,
                "net_worth": self.total_net_worth,
                "net_worth_delta": net_worth_delta,
                "buyNhold_balance": self.buyNhold_balance,
                "buyNhold_delta": buyNhold_delta,
                "actual_profit": self.total_net_worth - self.buyNhold_balance,
                "progress": (net_worth_delta+1)/(buyNhold_delta+1)
            }
