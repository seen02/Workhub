import fs from 'node:fs';
const file='.local/compose.json',config=JSON.parse(fs.readFileSync(file));
const tag=process.argv[2]||'analytics-overview-20261001';
for(const service of ['outline','workhub']){
 config.services[service].environment.OUTLINE_ANALYTICS_ENABLED='true';
 config.services[service].image=`unified-work-assistant/${service}:${tag}`;
}
fs.writeFileSync(file,JSON.stringify(config,null,2)+'\n');
console.log('Configured Outline and Workhub analytics images and independent feature flags.');
