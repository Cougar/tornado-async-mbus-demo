Clone repo
```shell
git clone --recurse-submodules https://github.com/Cougar/tornado-async-mbus-demo.git
```

Run in shell
```shell
pip install -r requirements.txt
cp /usr/lib/libmbus.so .
./demo.py
```

Run in docker container
```shell
docker run -ti --rm -v ${PWD}:/app -v /usr/lib64/libmbus.so.0.0.8:/usr/lib/libmbus.so.0:ro -v /usr/lib64/libmbus.so.0.0.8:/usr/lib/libmbus.so:ro -v /dev:/dev --privileged -p 8888:8888 python:3.6 /bin/bash
cd /app
pip install -r requirements.txt
cp /usr/lib/libmbus.so .
./demo.py
```

Open http://127.0.0.1:8888/ to see some fancy stats

If app crases then run this fix:
```
sed -i 's/^.\(.*self._libc.free.*\)/#\1/' python-mbus/mbus/MBus.py
```
