from Environment import *
import numpy as np
import pandas as pd
from matplotlib import pyplot as plt

MAX_WINDOW = 180
LARGE_WINDOW = 90
MID_WINDOW = 60
SMALL_WINDOW = 30
MIN_WINDOW = 7

env = Environment()
currentDate = EARLIEST_DATE+datetime.timedelta(days=SMALL_WINDOW-1) # SMALL_WINDOW: 30 days
etfList = ["S&P 500", "Shanghai Composite", "Bovespa", "DAX", "Nifty 50"]
marketName = "MSCI World"

def getBeta(etfName, marketName):
    smallestEtfDate = env.db[etfName].find_one(sort=[("Date", 1)])["Date"]
    smallestMarketDate = env.db[marketName].find_one(sort=[("Date", 1)])["Date"]
    earliestDate = max(smallestEtfDate,smallestMarketDate,EARLIEST_DATE)
    currentDate = earliestDate + datetime.timedelta(days=SMALL_WINDOW - 1)  # SMALL_WINDOW: 30 days
    dbResult = env.getRecordFromEndLengthByETFList(
        todayDate=datetime.datetime.now(),
        endDate=currentDate,
        length=SMALL_WINDOW-1,
        etfList=[etfName, marketName])
    if len(dbResult[etfName]) != len(dbResult[marketName]):
        delta = len(dbResult[etfName]) - len(dbResult[marketName])
        if delta > 0: # etf got more data:
            for i in range(delta):
                dbResult[marketName].insert(0, dbResult[marketName][0])
        else: # market got more data:
            for i in range(abs(delta)):
                dbResult[etfName].insert(0, dbResult[etfName][0])

    currentDate += datetime.timedelta(days=1)
    betaList = []

    counter = 0

    while currentDate < LATEST_DATE:
        # 1. Push the record of currentDate as the first item of dbResult
        newResult = env.getRecordFromStartLengthByETFList(datetime.datetime.now(), currentDate, 1, [etfName, marketName])
        if newResult[etfName]: # If there IS a new record
            dbResult[etfName].insert(0, newResult[etfName][0])
            if newResult[marketName]: # The dimension must match
                dbResult[marketName].insert(0, newResult[marketName][0])
            else:
                dbResult[marketName].insert(0, dbResult[marketName][0])


        marketChange = np.array([d['Change'] for d in dbResult[marketName]])
        etfChange = np.array([d['Change'] for d in dbResult[etfName]])
        beta = (np.cov(etfChange,marketChange)[0][1])/np.var(marketChange)
        betaList.append({"date": currentDate, "beta": beta})
        currentDate += datetime.timedelta(days=1)

        if counter%200 == 0:
            print(counter, beta)
        counter += 1

    return betaList


def getStd(etfName, marketName):
    currentDate = EARLIEST_DATE + datetime.timedelta(days=SMALL_WINDOW - 1)  # SMALL_WINDOW: 30 days
    dbResult = env.getRecordFromEndLengthByETFList(
        todayDate=datetime.datetime.now(),
        endDate=currentDate,
        length=SMALL_WINDOW-1,
        etfList=[etfName, marketName])
    if len(dbResult[etfName]) != len(dbResult[marketName]):
        delta = len(dbResult[etfName]) - len(dbResult[marketName])
        if delta > 0: # etf got more data:
            for i in range(delta):
                dbResult[marketName].insert(0, dbResult[marketName][0])
        else: # market got more data:
            for i in range(abs(delta)):
                dbResult[etfName].insert(0, dbResult[etfName][0])

    currentDate += datetime.timedelta(days=1)
    betaList = []

    counter = 0

    while currentDate < LATEST_DATE:
        # 1. Push the record of currentDate as the first item of dbResult
        newResult = env.getRecordFromStartLengthByETFList(datetime.datetime.now(), currentDate, 1, [etfName, marketName])
        if newResult[etfName]: # If there IS a new record
            dbResult[etfName].insert(0, newResult[etfName][0])
            if newResult[marketName]: # The dimension must match
                dbResult[marketName].insert(0, newResult[marketName][0])
            else:
                dbResult[marketName].insert(0, dbResult[marketName][0])


        marketChange = np.array([d['Change'] for d in dbResult[marketName]])
        etfChange = np.array([d['Change'] for d in dbResult[etfName]])
        beta = (np.cov(etfChange,marketChange)[0][1])/np.var(marketChange)
        betaList.append({"date": currentDate, "beta": beta})
        currentDate += datetime.timedelta(days=1)

        if counter%200 == 0:
            print(counter, beta)
        counter += 1

    return betaList

for etfName in etfList:
    betaList = getBeta(etfName, marketName)
    df = pd.DataFrame(betaList)
    plt.plot(df['date'], df['beta'], label=etfName)
plt.legend()
plt.show()
