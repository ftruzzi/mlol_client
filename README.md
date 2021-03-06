A Python client for interfacing with MLOL (medialibrary.it)

**Note: This is still a beta version, features and API are subject to change until first release.**

Any feedback is welcome!

## Features
- Public (medialibrary.it) and private (yourlibrary.medialibrary.it) access
- Book search and download (initial support, only .epub/.acsm)
- Page-level (coarse) and book-level (detailed) scraping

## Installation
```python
pip install -r requirements.txt
python setup.py install
```

## Usage examples
```python
from mlol_client import MLOLClient

# public
mlol = MLOLClient()

# authenticated
mlol = MLOLClient(domain="your_library.medialibrary.it", username="your_username", password="your_password")
```

Note: the `search_books` method returns a generator of pages, which are lists of books, as this is how results
are presented on the MLOL website. This means that you should make sure you have fetched all the pages before assuming
the search results don't have what you're looking for, unless you're searching by ID (e.g. ISBN) or exact title.

- Scrape all books
    ```python
    books = []
    page_generator = mlol.search_books("")
    for page in page_generator:
        books += page
    ```

- Download a book
    ```python
    if results := next(mlol.search_books("9788845982484")):
        book_file = mlol.download_book(results[0])
        
        with open("spillover.acsm", "wb") as f:
            f.write(book_file)
    ```
  
- Simple search
    ```python
    results = next(mlol.search_books("Quammen"))
    print(results[1])
    # <mlol_client.MLOLBook: {'id': '150216322', 'title': "L'albero intricato", 'authors': "['David Quammen']"}>
    ```
  
- Deep search (slower, includes book details)
  ```python
  results = next(mlol.search_books("Quammen", deep=True))
  print(results[1])
  # <mlol_client.MLOLBook: {'id': '150216322', 'title': "L'albero intricato", 'authors': "['David Quammen']", 'status': 'available', 'publisher': 'Adelphi', 'ISBNs': "['9788845982460', '9788845934803']", 'language': 'italiano', 'description': 'A guidare la mano di Darwin mentre nel 1837 tracci...', 'year': '2020'}>
  ```
