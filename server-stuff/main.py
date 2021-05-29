import flask
import pymongo
import pymorphy2
from flask import Flask, request, jsonify, Response
from pymongo import MongoClient
from bson import json_util
from mlxtend.frequent_patterns import apriori, fpgrowth, fpmax, association_rules
import pandas as pd

from yargy import (
    Parser,
    rule, or_, and_, not_,
)

from yargy.predicates import (
    caseless, type, gram, normalized,
    in_, in_caseless, dictionary
)

from yargy.pipelines import (
    caseless_pipeline,
    morph_pipeline
)
from yargy.interpretation import (
    fact,
    attribute
)
from yargy import interpretation as interp

INT = type('INT')

from word2numberi18n import w2n
import os

try:
    client = MongoClient('mongodb://localhost:27017/', )
    client.server_info()
    db = client["mainAPI"]
    print("DB CONNECTED")
    print(flask.__version__)
except pymongo.errors.ServerSelectionTimeoutError as err:
    print(err)

app = Flask(__name__)


def transformCursorToList(cursor):
    res = []
    for doc in cursor:
        res.append(doc)
    return res


def getAllcategories(categRaw):
    categories = transformCursorToList(categRaw)
    allCategories = {}
    for category in categories:
        allCategories[category['name']] = category
    return allCategories

def getCategoriesFromRequest(categoriesList, request):
    Item = fact(
        'item',
        ['amount', 'category', 'vendor']
    )

    TYPE = morph_pipeline(categoriesList)

    ITEM_Category = rule(
        TYPE.interpretation(
            Item.category
        )
    ).interpretation(
        Item
    )

    parser = Parser(ITEM_Category)
    match = parser.find(request)
    foundCategoriesNames = []
    morph = pymorphy2.MorphAnalyzer()
    for match in parser.findall(request):
        for category in [_.value for _ in match.tokens]:
            categoryName = morph.parse(category)[0].normal_form.upper()
            if categoryName not in foundCategoriesNames:
                foundCategoriesNames.append(categoryName)
    return foundCategoriesNames
def getVendorList(data):
    vendorList = []
    vendorValues = list(data.values())
    for alt in vendorValues:
        for value in alt:
            vendorList.append(value)
    return vendorList

def findVendorData(vendorData,vendor):
    for vendorName in vendorData.keys():
        if(vendor.upper() in vendorData[vendorName]):
            return vendorName
    return ""

def getItemData(categoryData,searchReq):
    Item = fact(
        'item',
        ['amount', 'unit','category', 'vendor']
    )
    LITERALS = {
        'один': 1,
        'два': 2,
        'три': 3,
        'четыре': 4,
        'пять': 5,
        'шесть': 6,
        'семь': 7,
        'восемь': 8,
        'девять': 9,
    }


    CATEGORY = morph_pipeline([categoryData["name"]])
    VENDOR = morph_pipeline(getVendorList(categoryData["vendorlist"][0]))
    UNIT = morph_pipeline(categoryData["unit"])
    AMOUNT = dictionary(LITERALS).interpretation(
        interp.normalized().custom(LITERALS.get)
    )

    AMOUNT_NUM = INT.interpretation(
        interp.custom(int)
    )

    ITEM_MISC = rule(
        AMOUNT.interpretation(
            Item.amount
        ).optional(),
        AMOUNT_NUM.interpretation(
            Item.amount
        ).optional(),
        UNIT.interpretation(
            Item.unit
        ).optional(),
        CATEGORY.interpretation(
            Item.category
        ),
        VENDOR.interpretation(
            Item.vendor
        ).optional()
    ).interpretation(
        Item
    )

    morph = pymorphy2.MorphAnalyzer()
    parser = Parser(ITEM_MISC)
    AllItemsData = []
    for match in parser.findall(searchReq):
        structItemData ={
            "vendor":findVendorData(categoryData["vendorlist"][0],match.fact.vendor),
            "category":morph.parse(match.fact.category)[0].normal_form.upper(),
            "amount":match.fact.amount,
            "unit":match.fact.unit,
        }
        AllItemsData.append(structItemData)
    return {categoryData["name"]: AllItemsData}


def normalizeDF(DF):
    DF["itemCount"] = DF.groupby(["userID", "itemID"])['categoryID'].transform('count')
    DF = DF[DF.duplicated(keep=False)]
    newDF = DF
    newDF = newDF.iloc[0:0]
    for userID in DF.userID.unique():
        DF["itemorderfreq"] = (
                    DF.itemCount / DF[DF.userID == userID].groupby(["userID"]).count()['itemCount'].to_list()[0])
        temp = DF[DF.userID == userID].sort_values(by="itemorderfreq", ascending=False).head(5)
        newDF = newDF.append(temp)
    return newDF.drop(["itemCount", "itemorderfreq"], axis=1).reset_index()

@app.route('/tokenize', methods=['POST'])
def tokenize():
    if not request.is_json:
        print('not a json')
        return 'not a json', 400
    reqData = request.get_json()  # get all data from request
    if not "searchReq" in reqData:
        print('no request')
        return 'no request', 400
    if not "categories" in reqData:
        print('no categories')
        return 'no categories',400

    categRaw = transformCursorToList(db.categories.find())  # Get raw categories from DB

    allCategories = getAllcategories(reqData["categories"])
    print(reqData["categories"])
    foundCategories = getCategoriesFromRequest(allCategories,reqData["searchReq"])

    res = []

    for category in foundCategories:
        res.append(getItemData(allCategories[category],reqData["searchReq"]))

    return Response(
        json_util.dumps(res),
        mimetype='application/json'
    )
@app.route('/recomenditem', methods=['POST'])
def recomendItem():
    reqData = request.get_json()  # get all data from reques
    orderList = db["orders"]
    data = transformCursorToList(orderList.find())
    newData = []
    for order in data:
        for iteminfo in order['order']:
            item = iteminfo['data']
            newData.append({"userID": order["userID"], "partnerID": order["partnerID"], "itemID": item["_id"],
                            "itemName": item["name"],"categoryID":item['category_id'], "manufacturerID": item["manufacturer"]["id"],
                            "manufacturerName": item["manufacturer"]["name"]})
    DF = pd.DataFrame(newData)
    DF = normalizeDF(DF)
    data_by_item = DF.groupby(['userID'])['itemID'].apply(','.join).reset_index()
    data_by_item_dummies = data_by_item['itemID'].str.get_dummies(',')
    frequent_itemsets = apriori(data_by_item_dummies, min_support=0.02, use_colnames=True)
    frequent_itemsets.sort_values(by=['support'], ascending=False).head(1)
    rules = association_rules(frequent_itemsets, metric="confidence", min_threshold=0.1)
    possibleItems = rules[rules["antecedents"] == {reqData["itemID"]}]
    alternativeItems = possibleItems.sort_values(by=['lift', 'conviction'], ascending=[False, True]).head(5)
    result = alternativeItems.explode('consequents').reset_index(drop=True)
    return Response(
        json_util.dumps(list(dict.fromkeys(result['consequents'].to_list()))),
        mimetype='application/json'
    )