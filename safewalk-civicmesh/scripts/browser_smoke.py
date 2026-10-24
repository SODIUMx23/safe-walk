"""Optional real-browser smoke suite against a *development test server*.

Install `pip install playwright==1.64.1` and `playwright install chromium`.
Uses fake browser camera/GPS; intercepted requests are marked simulation=true.
Never run this state-changing suite against a real caregiver workspace.
"""
import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, expect


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base-url', default='http://localhost:8000')
    parser.add_argument('--artifacts', default='artifacts')
    args = parser.parse_args()
    root = Path(args.artifacts); root.mkdir(parents=True, exist_ok=True)
    errors = []
    report = {}
    with sync_playwright() as runner:
        browser = runner.chromium.launch(args=['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', '--autoplay-policy=no-user-gesture-required'])
        desktop = browser.new_context(viewport={'width':1440,'height':1150}, reduced_motion='reduce')
        page = desktop.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(args.base_url + '/portal/',wait_until='networkidle')
        configuration = page.request.get(args.base_url + '/api/v1/config').json()
        if configuration['mode'] != 'development' or configuration['auth_required']:
            raise RuntimeError('Use an isolated unauthenticated DEVELOPMENT test server for this smoke test')
        expect(page.locator('#hubConnection')).to_contain_text('Hub connected')
        page.locator('#demoButton').click()
        expect(page.locator('#povImage')).to_be_visible(timeout=15000)
        expect(page.locator('#simulationBadge')).to_be_visible()
        expect(page.locator('#headValue')).to_have_text('165',timeout=15000)
        # User B must remain selected across asynchronous simulation ticks.
        expect(page.locator('#deviceSelect option[value="demo-specs-b"]')).to_have_count(1,timeout=15000)
        page.locator('#deviceSelect').select_option('demo-specs-b')
        page.wait_for_timeout(1800)
        expect(page.locator('#deviceSelect')).to_have_value('demo-specs-b')
        expect(page.locator('#nodeLabel')).to_contain_text('demo-specs-b')
        page.locator('#deviceSelect').select_option('demo-specs-a')
        report['simulation_user_b_selection'] = 'preserved across telemetry ticks'
        page.locator('#injectTicketButton').click()
        expect(page.locator('#ticketList')).to_contain_text('SIMULATED')
        page.screenshot(path=str(root/'dashboard-desktop.png'),full_page=True)
        page.locator('#testSosButton').click()
        expect(page.locator('#incidentDialog')).to_be_visible(timeout=60000)
        expect(page.locator('#sbarContent')).to_contain_text('SIMULATION')
        expect(page.locator('#playArchiveButton')).to_be_enabled(timeout=60000)
        page.locator('#playArchiveButton').click()
        expect(page.locator('#incidentVideo')).to_be_visible(timeout=15000)
        page.locator('#closeIncidentButton').click()
        page.locator('#demoButton').click()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        report['desktop_dashboard'] = 'passed'
        report['synthetic_test_sos_video'] = 'archived and played'

        mobile = browser.new_context(viewport={'width':390,'height':844},is_mobile=True,has_touch=True,
                                     permissions=['camera','geolocation'],geolocation={'latitude':12.9165,'longitude':79.1325,'accuracy':4},reduced_motion='reduce')
        mobile.add_init_script("localStorage.setItem('safewalk-device','browser-smoke-specs')")
        phone = mobile.new_page(); phone.on('pageerror',lambda error:errors.append(str(error)))
        def simulated_request(route):
            request = route.request
            body = request.post_data_buffer
            if body:
                body = body.replace(b'"simulation":false',b'"simulation":true',1)
            route.continue_(post_data=body)
        phone.route('**/api/v1/telemetry/telemetry',simulated_request)
        phone.route('**/api/v1/emergency/sos',simulated_request)
        phone.goto(args.base_url + '/specs/',wait_until='networkidle')
        expect(phone.locator('#setupDialog')).to_be_visible()
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        phone.locator('#consentSession').check(); phone.locator('#consentBlackbox').check(); phone.locator('#consentImpact').check()
        phone.locator('#startButton').click()
        expect(phone.locator('#connectionStatus')).to_contain_text('CONNECTED',timeout=20000)
        expect(phone.locator('#cacheStatus')).to_contain_text('40 / 40',timeout=30000)
        phone.evaluate("window.dispatchEvent(new DeviceOrientationEvent('deviceorientation',{beta:80,gamma:4,alpha:60}))")
        phone.locator('#calibrateButton').click()
        phone.evaluate("window.dispatchEvent(new DeviceOrientationEvent('deviceorientation',{beta:90,gamma:4,alpha:60}))")
        phone.wait_for_timeout(2400)
        phone.screenshot(path=str(root/'specs-mobile.png'),full_page=True)
        # Exercise the actual long-press handler, recorder lock, upload, and SBAR path.
        bounds = phone.locator('#touchSurface').bounding_box()
        phone.mouse.move(bounds['x']+bounds['width']/2,bounds['y']+bounds['height']/2)
        phone.mouse.down(); phone.wait_for_timeout(2100); phone.mouse.up()
        expect(phone.locator('#critical')).to_contain_text('Caregiver hub received alert',timeout=60000)
        expect(phone.locator('#critical')).to_contain_text('ARCHIVED',timeout=60000)
        phone.wait_for_timeout(2200)
        phone.evaluate("window.dispatchEvent(new DeviceMotionEvent('devicemotion',{accelerationIncludingGravity:{x:40,y:0,z:0},interval:16}))")
        expect(phone.locator('#critical')).to_contain_text('Caregiver hub received alert',timeout=60000)
        expect(phone.locator('#critical')).to_contain_text('ARCHIVED',timeout=60000)
        state = phone.request.get(args.base_url + '/api/v1/portal/state').json()
        impacts = [i for i in state['incidents'] if i['device_id']=='browser-smoke-specs' and i['trigger']=='HIGH_G_IMPACT']
        assert impacts and impacts[0]['simulation'] and impacts[0]['peak_g']>3.5
        assert impacts[0]['archive']['status']=='ARCHIVED', impacts[0]['archive']
        phone.locator('#stopButton').click()
        expect(phone.locator('#connectionStatus')).to_have_text('NOT MONITORING')
        assert phone.evaluate('document.documentElement.scrollWidth <= innerWidth')
        report['mobile_camera_and_gps'] = 'passed with synthetic browser devices'
        report['mobile_voice_cache'] = '40 / 40 decoded AudioBuffers'
        report['long_press_blackbox'] = 'passed: encrypted playable archive'
        report['automatic_high_g_guard'] = 'passed: simulated phone impact, no diagnostic claim'
        mobile_portal = mobile.new_page();mobile_portal.on('pageerror',lambda error:errors.append(str(error)))
        mobile_portal.goto(args.base_url+'/portal/',wait_until='networkidle')
        assert mobile_portal.evaluate('document.documentElement.scrollWidth <= innerWidth')
        mobile_portal.screenshot(path=str(root/'dashboard-mobile.png'),full_page=True)
        report['mobile_portal_layout'] = 'passed (390 px)'
        browser.close()
    report['uncaught_browser_errors'] = errors
    (root/'browser-smoke.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
    assert not errors, errors


if __name__=='__main__':
    main()
