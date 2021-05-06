import flask
import pymongo
import pymorphy2
from flask import Flask, request, jsonify, Response
from pymongo import MongoClient
from bson import json_util

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

try:
    client = MongoClient('mongodb://localhost:27017/', )
    client.server_info()
    db = client['metroDB']
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
            foundCategoriesNames.append(categoryName)

    categoriesList[categoryName]["vendorlist"]

    return foundCategoriesNames

def getItemData(categoryData,searchReq):
    Item = fact(
        'item',
        ['amount', 'unit','category', 'vendor']
    )

    CATEGORY = morph_pipeline([categoryData["name"]])
    VENDOR = morph_pipeline(categoryData["vendorlist"])
    UNIT = morph_pipeline(["буханка","буханка"])
    AMOUNT = INT.interpretation(
        interp.custom(int)
    )

    ITEM_MISC = rule(
        AMOUNT.interpretation(
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

    parser = Parser(ITEM_MISC)
    itemsData = []
    for match in parser.findall(searchReq):
        for itemData in [_.value for _ in match.tokens]:
            itemsData.append(itemData)
    return itemsData


@app.route('/tokenize', methods=['POST'])
def tokenize():
    if not request.is_json:
        return 'not a json', 400
    reqData = request.get_json()  # get all data from request
    if not "searchReq" in reqData:
        return 'no request', 400

    categRaw = transformCursorToList(db.categories.find())  # Get raw categories from DB

    allCategories = getAllcategories(categRaw)

    foundCategories = getCategoriesFromRequest(allCategories,reqData["searchReq"])

    res = []

    for category in foundCategories:
        res.append(getItemData(allCategories[category],reqData["searchReq"]))

    return Response(
        json_util.dumps(res),
        mimetype='application/json'
    )
