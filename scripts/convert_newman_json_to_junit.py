import json
import sys
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

infile = sys.argv[1] if len(sys.argv) > 1 else 'reports/newman-notify-lab04-full.json'
out_xml = sys.argv[2] if len(sys.argv) > 2 else 'reports/newman-notify-lab04-full.xml'
out_html = sys.argv[3] if len(sys.argv) > 3 else 'reports/newman-notify-lab04-full.html'

with open(infile, 'r', encoding='utf-8') as f:
    data = json.load(f)

collection = data.get('collection', {}).get('info', {}).get('name', 'newman')
run = data.get('run', {})
executions = run.get('executions', [])

testsuite = Element('testsuite')
testsuite.set('name', collection)

total = len(executions)
failures = 0

for ex in executions:
    req_name = ex.get('item', {}).get('name', 'request')
    testcase = SubElement(testsuite, 'testcase')
    testcase.set('classname', collection)
    testcase.set('name', req_name)
    assertions = ex.get('assertions', [])
    for a in assertions:
        if a.get('error'):
            failures += 1
            failure = SubElement(testcase, 'failure')
            failure.set('message', a.get('assertion', 'failure'))
            failure.text = a.get('error', {}).get('message', '')

# prettify
rough_string = tostring(testsuite, 'utf-8')
reparsed = minidom.parseString(rough_string)
pretty = reparsed.toprettyxml(indent="  ")

with open(out_xml, 'w', encoding='utf-8') as f:
    f.write(pretty)

# Simple HTML report
html_lines = [
    '<!doctype html>',
    '<html><head><meta charset="utf-8"><title>Newman Report</title></head><body>',
    f'<h1>Newman Report: {collection}</h1>',
    f'<p>Requests executed: {total}</p>',
    f'<p>Failures: {failures}</p>',
    '<table border="1" cellpadding="4" cellspacing="0">',
    '<tr><th>Request</th><th>Status</th><th>Assertions</th></tr>'
]
for ex in executions:
    req_name = ex.get('item', {}).get('name', '')
    assertions = ex.get('assertions', [])
    status = ex.get('response', {}).get('status', '')
    passed = all(a.get('error') is None for a in assertions)
    html_lines.append(f'<tr><td>{req_name}</td><td>{status}</td><td>{"pass" if passed else "fail"}</td></tr>')
html_lines.append('</table></body></html>')

with open(out_html, 'w', encoding='utf-8') as f:
    f.write('\n'.join(html_lines))

print('Wrote', out_xml, 'and', out_html)
