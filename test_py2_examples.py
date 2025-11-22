#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Python 2 Code Examples for Testing py2to3 Migration Server
These examples contain various Python 2 patterns that need migration.
"""

# 1. Print statements
print("Hello, World!")
print("Multiple", "values", "here")
print("With trailing comma", end=' ')
print("Error message", file=sys.stderr)

# 2. Unicode and string handling
name = "Unicode string"
data = "Regular string"
result = str(data)
if isinstance(name, str):
    print("Is a string")

# 3. Long integers
big_number = 1234567890
another = 0xDEADBEEF

# 4. Range functions
for i in range(10):
    print(i)

numbers = list(range(100))  # This returns a list in Python 2
lazy_numbers = range(1000000)  # Memory efficient

# 5. Dictionary methods
my_dict = {'a': 1, 'b': 2, 'c': 3}

for key, value in my_dict.items():
    print(key, value)

for key in my_dict.keys():
    print(key)

for value in my_dict.values():
    print(value)

if 'a' in my_dict:
    print("Found it!")

# 6. Input functions
name = input("Enter your name: ")
age = eval(input("Enter your age: "))  # Dangerous in Python 2!

# 7. Exception handling (old syntax)
try:
    x = 1 / 0
except ZeroDivisionError as e:
    print("Error:", e)

try:
    risky_operation()
except Exception as error:
    print(error)

# 8. Raise statements (old syntax)
raise ValueError("Something went wrong")
raise TypeError("Wrong type")

# 9. exec and execfile
exec("print 'executed'")
exec(compile(open("script.py", "rb").read(), "script.py", 'exec'))

# 10. reduce and apply (moved in Python 3)
from operator import add
from functools import cmp_to_key
from functools import reduce
total = reduce(add, [1, 2, 3, 4, 5])

def greet(name, greeting="Hello"):
    print(greeting, name)

greet(*["World"], **{"greeting": "Hi"})

# 11. Comparison operators
if x != y:  # Old not-equal syntax
    print("Not equal")

# 12. Division
result = 5 / 2  # Integer division in Python 2 = 2
precise = 5.0 / 2  # Float division = 2.5

# 13. Map and filter return lists
squares = [x**2 for x in [1, 2, 3]]  # Returns list in Python 2
evens = [x for x in [1, 2, 3, 4] if x % 2 == 0]  # Returns list

# 14. Class definitions
class OldStyleClass:
    """Old-style class (no object inheritance)"""
    def __init__(self):
        pass

class NewStyleClass(object):
    """New-style class"""
    pass

# 15. Octal literals
octal = 0o755  # Old octal syntax

# 16. Backticks for repr
x = 42
s = repr(x)  # Same as repr(x)

# 17. Sorting with cmp
def compare(a, b):
    return cmp(a, b)

sorted_list = sorted([3, 1, 2], key=cmp_to_key(compare))

# 18. File handling
f = file("data.txt", "r")  # file() is gone in Python 3
content = f.read()
f.close()

# 19. urllib and urllib2
import urllib.request, urllib.parse, urllib.error
import urllib.request, urllib.error, urllib.parse

response = urllib.request.urlopen("http://example.com")
params = urllib.parse.urlencode({"key": "value"})

# 20. ConfigParser (renamed)
import configparser
config = configparser.ConfigParser()

# 21. Queue (renamed)
import queue
q = queue.Queue()

# 22. StringIO and cStringIO
import io
import io

buffer1 = io.StringIO()
buffer2 = io.StringIO()

# 23. More print variations
print()  # Just newline
print("Hello", end=' '); print("World")  # Same line with semicolon
print("%s: %d" % ("Count", 42))  # String formatting (still works but %)