from pipeline.sources import HackerNewsSource


class Response:
    content_type = "text/html"

    def __init__(self, text):
        self.text = text


class Client:
    def __init__(self):
        self.calls = []

    def get(self, url, source):
        self.calls.append(url)
        if "submitted" in url:
            return Response('<a class="titleline" href="item?id=999"><span>Ask HN: Who is hiring? (November 2026)</span></a>')
        if "id=999" in url and "next=1" not in url:
            return Response('''<tr class="comtr" id="100"><div class="commtext">Acme | Senior Data Engineer | Remote US<p>Python and SQL</p></div></tr><a class="morelink" href="item?id=999&next=1">More</a>''')
        return Response('<tr class="comtr" id="101"><div class="commtext">Beta | ML Platform Engineer | Seattle, US</div></tr>')


def test_hacker_news_html_and_more_pagination():
    source = HackerNewsSource(Client())
    records = source.fetch()
    assert [record.source_id for record in records] == ["100", "101"]
    assert records[0].company == "Acme"
    assert records[1].location_text == "Seattle, US"
