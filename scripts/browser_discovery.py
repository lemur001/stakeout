"""Exercise discovery through real UI and HTTP with deterministic, unpaid source fixtures."""
from app.prospecting.worker import DiscoveryWorker
from app.prospecting.service import Discovery

class BrowserSources:
    def page(self,url):
        if url.endswith('sitemap.xml'):return url,'<urlset><url><loc>https://civic-history.org/</loc></url></urlset>'
        return url,'<html><title>Example Historical Society</title><p>Example Historical Society serves Chicago.</p><p>Copyright 2019</p><a href="/contact">Contact</a><p>hello@civic-history.org</p></html>'
    def json(self,url):
        if 'cdx' in url:return [['timestamp'],['20010101'],['20250101']],url
        if 'rdap' in url:return {'events':[{'eventAction':'registration','eventDate':'2000-01-01'}]},url
        raise AssertionError('Unexpected external request')

class UnpaidOnly:
    def call(self,*args):raise AssertionError('Browser test must never spend money')
    def opr(self,domain):return {'status':'not_configured','value':None}

def exercise_discovery(page,service,output):
    assert not service.snapshot()['cities'],'Exercise the first hunt in an empty workspace'
    page.goto(service.config.base_url+'/#discovery')
    page.get_by_role('button',name='New hunt',exact=True).click()
    page.get_by_role('heading',name='Start a prospect hunt',exact=True).wait_for()
    assert page.get_by_label('City',exact=True).input_value()==''
    assert page.get_by_label('State',exact=True).input_value()==''
    page.get_by_label('City',exact=True).fill('Chicago')
    page.get_by_label('State',exact=True).select_option('IL')
    page.emulate_media(reduced_motion='reduce')
    page.screenshot(path=str(output/'hunt-location-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Hunt form mobile overflow'
    page.screenshot(path=str(output/'hunt-location-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_label('Discover organizations from IRS filings',exact=False).uncheck()
    page.get_by_label('Include existing city records and AI research candidates',exact=True).uncheck()
    page.get_by_text('Add organizations from another source',exact=True).click()
    page.get_by_label('One organization per line',exact=False).fill('Example Historical Society | https://civic-history.org/ | https://city.example/clubs')
    page.get_by_label('I have permission to retrieve and retain these sources and provider results',exact=True).check()
    page.get_by_role('button',name='Start hunt',exact=True).click()
    page.get_by_role('button',name='Pause',exact=True).wait_for()
    cities=service.snapshot()['cities'];assert len(cities)==1
    chicago=cities[0];assert (chicago['name'],chicago['region'],chicago['timezone'])==('Chicago','IL','America/Chicago')
    assert Discovery(service).list()[0]['city_id']==chicago['id']
    worker=DiscoveryWorker(service,BrowserSources(),UnpaidOnly())
    worker.tick();worker.tick();worker.tick()
    page.reload()
    page.get_by_role('button',name='Example Historical Society',exact=True).wait_for()
    assert '1 of 1 candidates checked' in page.locator('#hunt-results').inner_text()
    assert 'Unknown' in page.locator('#hunt-table').inner_text()
    with page.expect_download() as download:
        page.get_by_role('link',name='Export hunt CSV',exact=True).click()
    export=output/'discovery-export.csv';download.value.save_as(export)
    assert 'Example Historical Society' in export.read_text(encoding='utf-8-sig')
    anonymous=page.context.browser.new_context(ignore_https_errors=True)
    export_path='/api/discovery/'+Discovery(service).list()[0]['id']+'/export.csv'
    assert anonymous.request.get(service.config.base_url+export_path).status==401
    anonymous.close()
    page.screenshot(path=str(output/'discovery-desktop.png'),full_page=True)
    page.emulate_media(reduced_motion='reduce')
    page.set_viewport_size({'width':390,'height':844})
    page.screenshot(path=str(output/'discovery-mobile.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'),'Discovery mobile overflow'
    page.set_viewport_size({'width':1440,'height':1000})
    page.get_by_role('button',name='Example Historical Society',exact=True).click()
    page.get_by_role('heading',name='Website findings',exact=True).wait_for()
    assert 'hello@civic-history.org' in page.locator('#sheet').inner_text()
    assert 'Activity and size evidence' in page.locator('#sheet').inner_text()
    assert 'Years represented in archive' in page.locator('#sheet').inner_text()
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
    # A large hunt must keep every row reachable, including pending/unknown results.
    discovery=Discovery(service);run=discovery.list()[0]
    discovery.add_targets(run,[{'name':f'Pagination candidate {n:03d}'} for n in range(51)])
    discovery.control(run['id'],'pause','browser-test')
    page.reload()
    page.get_by_role('button',name='Next 50',exact=True).click()
    assert 'Showing 51–52.' in page.locator('#hunt-table').inner_text()
    assert page.get_by_role('button',name='Next 50',exact=True).is_disabled()
    page.get_by_label('Filter organizations',exact=True).fill('Pagination candidate 050')
    assert 'Showing 1–1.' in page.locator('#hunt-table').inner_text()
    page.get_by_role('button',name='Pagination candidate 050',exact=True).wait_for()
    # Research reuses a city automatically; it never sends the user to "Add city".
    page.get_by_role('button',name='Investigate a city with AI',exact=True).click()
    assert page.get_by_label('City',exact=True).input_value()==''
    page.get_by_label('City',exact=True).fill(' chicago ')
    page.get_by_label('State',exact=True).select_option('IL')
    page.get_by_label('The research sources and search plan permit this storage and use',exact=True).check()
    page.get_by_role('button',name='Create research run',exact=True).click()
    page.get_by_role('heading',name='Research runs',exact=True).wait_for()
    assert len(service.snapshot()['cities'])==1
    assert service.snapshot()['research'][0]['city_id']==chicago['id']
    # Report imports also accept a new place without setup or a saved-city dropdown.
    page.get_by_role('button',name='Import report',exact=True).click()
    page.get_by_label('City',exact=True).fill('Seattle')
    page.get_by_label('State',exact=True).select_option('WA')
    page.get_by_label('Report title',exact=True).fill('Synthetic Seattle report')
    page.get_by_label('Report text',exact=True).fill('Synthetic civic organization report for Seattle. No real contact or provider data is included.')
    page.get_by_label('I have permission to process and store this report and its sources',exact=True).check()
    page.locator('#modal').get_by_role('button',name='Import report',exact=True).click()
    page.get_by_role('heading',name='Import a research report',exact=True).wait_for(state='hidden')
    seattle=next(c for c in service.snapshot()['cities'] if c['name']=='Seattle')
    assert seattle['region']=='WA' and seattle['timezone']=='America/Los_Angeles'
    assert len(service.snapshot()['cities'])==2
    # The hunt form stays editable even after cities exist; no first-city default.
    page.goto(service.config.base_url+'/#discovery')
    page.get_by_role('button',name='New hunt',exact=True).click()
    page.get_by_role('heading',name='Start a prospect hunt',exact=True).wait_for()
    assert page.get_by_label('City',exact=True).input_value()==''
    page.get_by_label('City',exact=True).fill('Des Plaines')
    page.get_by_label('State',exact=True).select_option('IL')
    page.get_by_role('button',name='Cancel',exact=True).click()
    assert len(service.snapshot()['cities'])==2,'Cancel must not save a city'
    print('Discovery browser passed: direct city/state search in an empty workspace, automatic city reuse, AI research/import locations, worker, rankings, evidence, review, CSV, pagination and mobile layout; no paid calls.')
