"""Exercise discovery through real UI and HTTP with deterministic, unpaid source fixtures."""
from app.prospecting.worker import DiscoveryWorker

class BrowserSources:
    def page(self,url):
        if url.endswith('sitemap.xml'):return url,'<urlset><url><loc>https://civic-history.org/</loc></url></urlset>'
        return url,'<html><title>Example Historical Society</title><p>Example Historical Society serves Lakeland.</p><p>Copyright 2019</p><a href="/contact">Contact</a><p>hello@civic-history.org</p></html>'
    def json(self,url):
        if 'cdx' in url:return [['timestamp'],['20010101'],['20250101']],url
        if 'rdap' in url:return {'events':[{'eventAction':'registration','eventDate':'2000-01-01'}]},url
        raise AssertionError('Unexpected external request')

class UnpaidOnly:
    def call(self,*args):raise AssertionError('Browser test must never spend money')
    def opr(self,domain):return {'status':'not_configured','value':None}

def exercise_discovery(page,service,output):
    page.goto(service.config.base_url+'/#discovery')
    page.get_by_role('button',name='New hunt',exact=True).click()
    page.get_by_label('Discover organizations from IRS filings',exact=False).uncheck()
    page.get_by_label('Include existing city records and AI research candidates',exact=True).uncheck()
    page.get_by_text('Add organizations from another source',exact=True).click()
    page.get_by_label('One organization per line',exact=False).fill('Example Historical Society | https://civic-history.org/ | https://city.example/clubs')
    page.get_by_label('I have permission to retrieve and retain these sources and provider results',exact=True).check()
    page.get_by_role('button',name='Start hunt',exact=True).click()
    page.get_by_role('button',name='Pause',exact=True).wait_for()
    worker=DiscoveryWorker(service,BrowserSources(),UnpaidOnly())
    worker.tick();worker.tick();worker.tick()
    page.reload()
    page.get_by_role('button',name='Example Historical Society',exact=True).wait_for()
    assert '1 of 1 candidates checked' in page.locator('#hunt-results').inner_text()
    assert 'Unknown' in page.locator('#hunt-table').inner_text()
    page.screenshot(path=str(output/'discovery-desktop.png'),full_page=True)
    page.emulate_media(reduced_motion='reduce')
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(output/'discovery-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Discovery mobile overflow'
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button',name='Example Historical Society',exact=True).click()
    page.get_by_role('heading',name='Website findings',exact=True).wait_for()
    assert 'hello@civic-history.org' in page.locator('#sheet').inner_text()
    page.get_by_role('button',name='Inspect sources',exact=True).click()
    page.get_by_role('heading',name='Discovery evidence',exact=True).wait_for()
    assert 'sitemap' in page.locator('#sheet').inner_text()
    page.get_by_role('button',name='Close dialog',exact=True).click()
    page.get_by_role('button',name='Review',exact=True).click()
    try:
        assert page.locator('#sheet select[name="campaign"]').input_value(timeout=5000)=='rebuild'
    except Exception:
        print('Discovery review error:',page.locator('#toasts').inner_text())
        print('Review panel:',page.locator('#sheet').inner_text()[:300])
        raise
    page.get_by_role('button',name='Close dialog',exact=True).click()
    print('Discovery browser passed: create hunt, durable worker, rankings, evidence, campaign review and desktop/mobile layout; no paid calls.')
