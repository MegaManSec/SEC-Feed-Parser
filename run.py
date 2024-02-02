#!/usr/bin/env python3
import sys
from collections import defaultdict
import re
from bs4 import BeautifulSoup
import requests
import feedparser

SEC_RSS_FEED = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=100&output=atom"
USER_AGENT = "Joshua Rogers Joshua@Joshua.Hu" # Format should be "(Company) Name Contact@Email.tld"


def get_rss_feed(feed_url):
    """
    Retrieve the entries for an rss feed.
    """

    headers = {'User-Agent': USER_AGENT}
    response = requests.get(feed_url, headers=headers)

    if response.status_code != 200:
        print(f"Error: Unable to fetch RSS feed. Status code: {response.status_code}", file=sys.stderr)
        return None

    feed = feedparser.parse(response.content)

    if 'entries' not in feed:
        print("Error: Unable to parse RSS feed.", file=sys.stderr)
        return None

    return feed.entries

def get_true_url(link):
    """
    Construct the true URL for the 1.05 filing and retrieve the content.
    Extract the text between the first occurrence of '<html' and the last occurrence of '</html>'.
    """

    # https://www.sec.gov/Archives/edgar/data/789019/000119312524011295/0001193125-24-011295-index.htm can be read by https://www.sec.gov/Archives/edgar/data/789019/000119312524011295/0001193125-24-011295.txt
    true_url = link.replace("-index.html", ".txt") # Should not be needed
    true_url = true_url.replace("-index.htm", ".txt")

    headers = {'User-Agent': USER_AGENT}
    response = requests.get(true_url, headers=headers)

    return response

def clean_non_ascii(text):
    """
    Cleans up a text and removes any non-ascii characters, and newlines.
    Also strip newlines.
    """
    non_ascii_pattern = re.compile(r'[^\x00-\x7F\n]') # Only ASCII + newline.

    return non_ascii_pattern.sub('', text).strip()

def parse_html(response_text):
    """
    Parse the HTML and remove any invalid characters and excessive whitespaces.
    Returns a string representation of the text response.
    """
    full_html = response_text.replace("&#160;", " ") # Replace annoying html space with space. May not actually be needed.

    full_html = clean_non_ascii(full_html)

    full_html = full_html.split('\n') # Split every new line into an element so we can strip each line properly.

    for line_num in range(len(full_html)):
        full_html[line_num] = full_html[line_num].strip() # Strip each line

    full_html = '\n'.join(full_html) # Re-join to form a string.

    return full_html

def fix_items(response_text):
    """
    Turns <tag>Item\n1.1</tag> into <tag>Item 1.1</tag>, for example.
    Turns I\ntem 1.1 into Item 1.1, for example.
    """

    pattern = r'Item.?.?\n.?.?(\d+\.\d+)'
    replacement_pattern = r' Item \1'

    full_html = re.sub(pattern, replacement_pattern, response_text, flags=re.IGNORECASE)

    pattern = r'I\ntem.?.?(\d+\.\d+)'
    replacement_pattern = r'Item \1'

    full_html = re.sub(pattern, replacement_pattern, full_html, flags=re.IGNORECASE)

    full_html = full_html.split('\n') # Split every new line into an element so we can strip each line properly.

    for line_num in range(len(full_html)):
        full_html[line_num] = full_html[line_num].strip() # Strip each line

    full_html = '\n'.join(full_html) # Re-join to form a string.

    return full_html

def find_item_nums(full_html):
    """
    Finds the item number given Item..\d.\d
    """
    pattern = re.compile(r'Item.?.?(\d+\.\d+)', flags=re.IGNORECASE)
    matches = pattern.findall(entry.summary)

    return matches

def get_section(full_html, section):
    """
    Get a section from the html
    """

    soup = BeautifulSoup(full_html, 'html5lib')
    found_sections = soup.find_all(section)

    return found_sections

def get_sections(full_html):
    """
    Find the sections which include the main part of the page.
    Either <XBRL /> or <DOCUMENT /> as a fallback.
    """

    found_xbrls = get_section(full_html, "xbrl")

    if len(found_xbrls) > 0:
        return found_xbrls

    found_documents = get_section(full_html, "document")

    return found_documents

def get_company_name(title):
    """
    Convert title into the proper company
    """

    company = title
    company = company.replace("8-K - ", "")
    company = company.replace(" (Filer)", "")

    return company

def get_html_text(html):
    text = html.get_text(separator='\n', strip=True)

    text = clean_non_ascii(text)
    text = text.split('\n')

    for line_num in range(len(text)):
        text[line_num] = text[line_num].strip()

    text = '\n'.join(text)

    return str(text)

def parse_items(full_html, items):
    documents = {}
    signature = []
    reached_sig = False

    sections = get_sections(full_html)

    if len(sections) == 0:
        print("Huh?! No XBRL/document tags found!\n", file=sys.stderr)
        return

    for section in sections:
        if reached_sig:
            break

        text = get_html_text(section)
        text = fix_items(text)

        item = None

        for line in text.split('\n'):
            split_items = re.split(r"^Item.?.?(\d+\.\d+)(?:\. )?", line, flags=re.IGNORECASE, maxsplit=1)

            if len(split_items) > 1 and reached_sig is False:
                item = split_items[1].lower() # the item number, "Item 1.1"
                rem_rext = split_items[2] # The remainder

                items[item].append(rem_rext) # items[1.1] = ("Data data data..")
            else:
                if split_items[0].lower() in ("SIGNA TURES".lower(), "SIGNATURE".lower(), "SIGNATURES".lower(), "Signature(s)".lower()) and reached_sig is False:
                    reached_sig = True
                    continue

                if item is None and reached_sig is False: # Lots of junk before the first item.
                    continue

                if len(split_items) != 1:
                    print(f"Huh?! Wrong length?!: {split_items}", file=sys.stderr) # Should be impossible?
                    continue

                if reached_sig is True: # Everything after "signature(s)" is a signature.
                    signature.append(split_items[0])
                    continue

                items[item].append(split_items[0]) # Not a signature, not a new "Item" split.

        for item_num in items:
            if len(items[item_num]) == 0:
                continue

            if item_num == "9.01".lower():
                for text_part in items[item_num]:
                    matches = re.findall(r'(?<!\bItem\s)(\d+\.\d+)', text_part, flags=re.IGNORECASE)
                    for match in matches:
                        if match not in documents:
                            documents[match] = ""

    return items, signature, documents


def parse_documents(full_html, documents):
    for found_document in get_section(full_html, "document"):
        found_document = clean_non_ascii(str(found_document))

        match = re.search(r'\n<TYPE>(EX-[\d\.]+)[0-9A-Za-z- ]*\n', found_document, re.IGNORECASE | re.DOTALL)

        if not match:
            continue

        document_title = match.group(1)

        match = re.search(r'\n<FILENAME>(.*?)\n', found_document, re.IGNORECASE | re.DOTALL)

        if match and ".pdf" in match.group(1).lower():
            print(f"Huh?! Skipping document {match.group(1)} due to pdf.\n", file=sys.stderr)
            continue

        if len(document_title) == 0 or document_title[-1] == '.' or document_title == "8-K":
            continue

        short_title = document_title.split('-')

        if len(short_title) == 2:
            short_title = short_title[1]
        else:
            short_title = document_title # short_title[0]

        if len(short_title) == 0 or short_title == ".":
            continue

        if short_title not in documents:
            print(f"Huh?! Found short_title {short_title} (title: {document_title}) in the document but we weren't expecting it.\n", file=sys.stderr)
            documents[short_title] = ""

        doc_soup = BeautifulSoup(found_document, 'html5lib')

        text = get_html_text(doc_soup.find('text'))
        text = clean_non_ascii(text)

        removed_title = False

        for line in text.split('\n'):
            if removed_title is False and line in (f"Exhibit {short_title}", document_title):
                removed_title = True
                continue
            documents[short_title] += f"{line} "

    return documents

def doit(entry):
    items = defaultdict(list)
    link = entry.link

    print("URL:", link, "\n")

    company = get_company_name(entry.title)
    response = get_true_url(entry.link)

    full_html = parse_html(response.text)
    full_html = fix_items(full_html)

    item_nums = find_item_nums(full_html)
    for item_num in item_nums:
        items[item_num] = []

    doity = False
    for item in items:
        if 'Item 1.05'.lower() in item.lower():
            doity = True
            break
    if not doity:
        return

    items, signature, documents = parse_items(full_html, items)

    documents = parse_documents(full_html, documents)


    for short_title in documents:
        if short_title == "104": # why?
            continue

        if len(documents[short_title]) == 0:
            # May have been a sub-part of a document
            if short_title in items["9.01"]:
                short_title_index = items["9.01"].index(short_title)
                matches = re.findall(r' exhibit (\d+\.\d+)', items["9.01"][short_title_index+1], flags=re.IGNORECASE)
                for match in matches:
                    if match in documents and match != short_title:
                        documents[short_title] = f"REF=={match}"
                        break


    prev_item = None
    for item_num in items:
        if len(items[item_num]) == 0:
            if prev_item is not None:
                if item_num in items[prev_item]:
                    print(f"Huh?! We needed to fix {item_num}, recovering data from {prev_item}", file=sys.stderr)
                    head = set()
                    tail = set()

                    # Find the index of item_num in the set
                    if item_num in items[prev_item]:
                        item_num_index = list(items[prev_item]).index(item_num)

                        # Create the 'head' and 'tail' as sets
                        head = set(list(items[prev_item])[:item_num_index])
                        tail = set(list(items[prev_item])[item_num_index + 1:])

                    # Update items[prev_item] with the 'head'
                    items[prev_item] = head

                    # Update items[item_num] with the 'tail'
                    items[item_num] = tail

        item_string = ' '.join(items[item_num]).strip()
        while len(item_string) > 0 and item_string[0] in (' ', '.'):
            item_string = item_string[1:]

        if len(item_string) == 0:
            print(f"Huh?! We were expecting item {item_num} but we didn't find it.\n", file=sys.stderr)
        else:
            print(f"Item: {item_num}: {item_string}\n")

        prev_item = item_num

    signature = ' '.join(signature)
    print(f"Signature: {signature}\n")

    for short_title in documents:
        if len(documents[short_title]) == 0:
            print(f"Huh?! We were expecting short_title {short_title} but we didn't find it.\n", file=sys.stderr)
            continue

        print(f"Document {short_title}: {documents[short_title]}\n")

    print("\n\n")

if __name__ == "__main__":
    feed = get_rss_feed(SEC_RSS_FEED)
    if feed is None:
        exit()

    for entry in feed:
#        print("")
#        continue
        doit(entry)
