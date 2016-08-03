import os
import sys         # for sys.exit
import time        # to get current timestamp
import threading   # for threads
import socket      # wifi sockets
import datetime    # for datetime column in db
import calendar

try:
    import sqlite3
    conn = sqlite3.connect("bluezchat.db") # create new database connection
except:
    print "Install sqlite3 first"

try:
    import gtk
    import gobject
    import gtk.glade  # gtk is interface, gobject is event handler for gtk
except:
    print "Please install gtk, gobject and glade packages for Python, exiting."
    print "sudo apt-get install python-gtk2 python-glade2 python-gobject"
    sys.exit()

try:
    import netifaces # this is required to get wifi IP and check if connected to wifi
except:
    print "Install netifaces"
    print "sudo easy_install netifaces"
    sys.exit()

bluetoothAvailability = None

# try to import bluetooth, if it is not found, disable bluetooth
try:
    import bluetooth
except:
    bluetoothAvailability = False
    print "I can\'t use bluetooth in your system, sorry mate :("

# try to open a temporary socket to test if bluetooth is on on the device
# if this raises an error, bluetooth is disabled on the device
if bluetoothAvailability != False:
    try:
        bluetoothAvailability = True
        tempSock = bluetooth.BluetoothSocket(bluetooth.L2CAP)
        tempSock.settimeout(1)
        tempSock.connect(("01:23:45:67:89:AB", 0x1001))
    except Exception as e:
        if "No route to host" in str(e):
            print "There's something wrong with bluetooth, disabling it"
            bluetoothAvailability = False

# try to get IP address of the device, if not wi-fi will be disabled
wifi_availability = None
try:
    print "IP: %s" % (netifaces.ifaddresses(netifaces.gateways()['default'][netifaces.AF_INET][1])[netifaces.AF_INET][0]['addr'])
    print "Wi-fi interface found"
    wifi_availability = True
except:
    print "Wi-fi is not connected, disabling..."
    wifi_availability = False

# print wfi and bluetooth status, if both are disabled exit
if wifi_availability and bluetoothAvailability:
    print "Wi-Fi and bluetooth are both nice and working."
elif wifi_availability:
    print "Wifi is working, bluetooth is not"
elif bluetoothAvailability:
    print "Bluetooth is nice and working, wi-fi is not."
else:
    print "You can't use this program without wifi or bluetooth, exiting..."
    sys.exit()

# *****************

GLADEFILE="bluezchat.glade"

# opens alert dialog
def alert(text, buttons=gtk.BUTTONS_NONE, type=gtk.MESSAGE_INFO):
    md = gtk.MessageDialog(buttons=buttons, type=type)
    md.label.set_text(text)
    md.run()
    md.destroy()

class BluezChatGui:
    def __init__(self):
        self.main_window_xml = gtk.glade.XML(GLADEFILE, "bluezchat_window")

        # connect our signal handlers
        dic = { "on_quit_button_clicked" : self.quit_button_clicked,
                "on_send_button_clicked" : self.send_button_clicked,
                "on_scan_button_clicked" : self.scan_button_clicked,
                "on_devices_tv_cursor_changed" : self.devices_tv_cursor_changed
                }

        self.main_window_xml.signal_autoconnect(dic)

        # prepare the floor listbox
        self.devices_tv = self.main_window_xml.get_widget("devices_tv")
        self.discovered = gtk.ListStore(gobject.TYPE_STRING, gobject.TYPE_STRING)
        self.devices_tv.set_model(self.discovered)
        renderer = gtk.CellRendererText()
        column1=gtk.TreeViewColumn("addr", renderer, text=0)
        column2=gtk.TreeViewColumn("name", renderer, text=1)
        self.devices_tv.append_column(column1)
        self.devices_tv.append_column(column2)

        self.quit_button = self.main_window_xml.get_widget("quit_button")
        self.scan_button = self.main_window_xml.get_widget("scan_button")

        self.send_button = self.main_window_xml.get_widget("send_button")
        self.main_text = self.main_window_xml.get_widget("main_text")
        self.text_buffer = self.main_text.get_buffer()

        self.input_tb = self.main_window_xml.get_widget("input_tb")     # message input
        self.input_tb2 = self.main_window_xml.get_widget("input_tb2")   # username input (for private messaging)

        self.listed_devs = []

        self.peers = {}         # holds peer sockets indexed by address
        self.sources = {}       # holds source variables for gobject watchers
        self.addresses = {}     # holds address, indexed by sockets
        self.hosts = {}         # holds wifi and bluetooth addresses for hostnames, indexed by hostnames
        self.messages = []      # holds previous messages
        self.thread_list = []   # holds threads

        # the listening sockets
        self.server_sock = None                     # bluetooth listening socket
        self.server_sock_wifi = None                # wifi listening socket
        self.hostname = socket.gethostname()        # machines hostname
        self.server_IP = None                       # wifi IP address
        self.server_IP_template = None              # wifi local ip address template 1xx.xx.xx. format, concat an integer and it becomes an IP address
        self.wifi_port = None                       # wifi listening port
        self.wifi = wifi_availability               # holds if wifi is available or not
        if wifi_availability:                       # if wifi is available
            self.server_IP = netifaces.ifaddresses(netifaces.gateways()['default'][netifaces.AF_INET][1])[netifaces.AF_INET][0]['addr'] # get server IP
            self.server_IP_template = self.server_IP[:9]    # get it's first 9 characters as template
            self.wifi_port = 12345                  # set some listening port
        self.bluetooth = bluetoothAvailability      # holds if bluetooth is available or not
        self.bluetoothConnType = bluetooth.L2CAP    # blutooth connection type, RFCOMM or L2CAP
        self.bluetoothPort = 0x1001                 # bluetooth listening port
        self.timeout = 10                           # bluetooth connection timeout

# --- gui signal handlers

    # quits the gui when quit button is clicked
    def quit_button_clicked(self, widget):
        gtk.main_quit()

    # scans for reachable bluetooth and wifi devices
    def scan_button_clicked(self, widget):
        self.quit_button.set_sensitive(False)
        self.scan_button.set_sensitive(False)

        # Inititiate WIFI Scan ##############################################
        # we first do the wifi scan because sometimes bluetooth discovery disables wifi connection

        if self.wifi:   # if wifi is enabled
            ip_ = 1
            while ip_ < 255:
                ip_ = ip_ + 1
                IP = self.server_IP_template + str(ip_) # create 1xx.xx.xx.i IP's
                if IP == self.server_IP:                # if IP is our own, continue
                    continue
                if IP in self.addresses.values():       # if already connected, continue
                    print "Already connected to %s" % IP
                    continue
                try:    # discover using threads
                    t = threading.Thread(target=self.discover, args=(IP,))
                    self.thread_list.append(t)
                except Exception as e:
                    template = "An exception of type {0} occured. Arguments:{1!r}"
                    mesg = template.format(type(e).__name__, e.args)
                    print mesg

            for thread in self.thread_list: # start all threads
                thread.start()

            for thread in self.thread_list: # then wait for them to finish
                thread.join()

            del self.thread_list[:]         # remove all threads
        else:
            "Wifi scan skipped, not connected to wifi."

        # Initiate bluetooth scan ###########################################
        
        if self.bluetooth:
            for addr, name in bluetooth.discover_devices (lookup_names = True): # discover nearby devices using library function
                if addr in self.addresses.values():
                    print "Already connected to %s" % addr
                    continue
                try:    # use threads to connect to bluetooth devices
                    t = threading.Thread(target=self.discover_bluetooth, args=(addr, name,))
                    self.thread_list.append(t)
                except Exception as e:
                    template = "An exception of type {0} occured. Arguments:{1!r}"
                    mesg = template.format(type(e).__name__, e.args)
                    print mesg

            for thread in self.thread_list:
                thread.start()

            for thread in self.thread_list:
                thread.join()

            del self.thread_list[:]

        self.quit_button.set_sensitive(True)
        self.scan_button.set_sensitive(True)

        print "Done"

    # starts when send button is clicked
    def send_button_clicked(self, widget):
        # we will send messages in the form: timestamp,our hostname,destination host name,message
        mtime = int(time.time())            # current timestamp, it is float make it integer
        host = self.hostname                # our hostname
        dest = self.input_tb2.get_text()    # destination is the value of textbox2
        message = self.input_tb.get_text()  # message is the vaue of textbox1
        
        # create data
        data = "%s,%s,%s,%s" % (mtime, host, dest, message)
        if len(data) == 0: return

        if dest != "":  # if destination is not everybody, "" means everybody
            if dest in self.hosts.keys():                   # if we see the destination
                if self.hosts[dest][0] != 0:                # if we see him/her via wifi
                    sock = self.peers[self.hosts[dest][0]]  # get wifi socket
                    sock.send(data + "\t")                  # send the message using wifi
                else:
                    sock = self.peers[self.hosts[dest][1]]  # get bluetooth socket
                    sock.send(data + "\t")                  # send over bluetooth
                print "Data sent to that host"
            else:       # if destination is one person but we cannot see him/her currently
                # we save the message to our database and send it when we can see the destination
                conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", (mtime, host, dest, message))
                conn.commit()
                print "Message queued, also sent to others."
                
                # also send the message to nearby devices
                self.messages.append(data)          # we append it to our list so we cannot process it again when it comes back to us
                for hostKey in self.hosts.keys():   # for everyhost we see
                    if hostKey == host:
                        continue
                    if self.hosts[hostKey][0] != 0:                 # try to send it over wifi
                        sock = self.peers[self.hosts[hostKey][0]]
                        sock.send(data + "\t")
                    else:
                        sock = self.peers[self.hosts[hostKey][1]]   # or bluetooth
                        sock.send(data + "\t")
        else:
            # same thing here, if message is sent to everybody, we send it to everybody
            self.messages.append(data)
            for hostKey in self.hosts.keys():
                if hostKey == host:
                    continue
                if self.hosts[hostKey][0] != 0:
                    sock = self.peers[self.hosts[hostKey][0]]
                    sock.send(data + "\t")
                else:
                    sock = self.peers[self.hosts[hostKey][1]]
                    sock.send(data + "\t")
        # clear the message input
        self.input_tb.set_text("")
        # print the message in our own program as our own
        self.add_text("\n[%s] %s: %s" % (self.get_time(datetime.datetime.fromtimestamp(mtime)), self.hostname, message))

    # fires when user clicks on any name in the connections list
    def devices_tv_cursor_changed(self, widget):
        (model, iter) = self.devices_tv.get_selection().get_selected()  # get who's selected
        self.input_tb2.set_text(model.get_value(iter, 1))               # set destination textbox as it
       

# --- network events
    # returns the message format for given data
    def get_data(self, mtime, host, dest, message):
        return str(mtime) + "," + host + "," + dest + "," + message + "\t"

    # returns the time format to print to messages, 18:06 for today or Aug 16 18:06 for other days etc.
    # uses datetime and calendar libraries
    def get_time(self, datetimeObj):
        now = datetime.datetime.now()
        if now.month == datetimeObj.month and now.day == datetimeObj.day and now.year == datetimeObj.year:
            return "%02s:%02s" % (datetimeObj.hour, datetimeObj.minute)
        else:
            return "%s %s %02s:%02s" % (calendar.month_abbr[datetimeObj.month], datetimeObj.day, datetimeObj.hour, datetimeObj.minute)

    # fires when someone try to connect us via bluetooth
    def incoming_connection(self, source, condition):
        sock, info = self.server_sock.accept()  # accept the socket
        address, psm = info                     # get it's address

        # add new connection to list of peers
        self.peers[address] = sock              # save it to peers
        self.addresses[sock] = address          # also save it address

        # gobject.io_add_watch adds an event handler for i/o on that socket
        # basically, when we receive some input from it, self.data_ready function is called
        source = gobject.io_add_watch (sock, gobject.IO_IN, self.data_ready)
        self.sources[address] = source          # add that to our event handlers list
        return True

    # fires when someone try to connect us via wifi
    def incoming_connection_wifi(self, source, condition):
        sock, addr = self.server_sock_wifi.accept()

        address = addr[0]
        if not address in self.addresses:
            # add new connection to list of peers
            self.peers[address] = sock
            self.addresses[sock] = address

            source = gobject.io_add_watch (sock, gobject.IO_IN, self.data_ready)
            self.sources[address] = source
            return True

    # fires when data is ready
    def data_ready(self, sock, condition):
        incoming_type = self.get_socket_type(sock)  # get incoming socket type
        # we read 1023 bytes here, so incoming message has a limitation
        # technically we can read the length then continue reading the message
        # via wifi sockets, but it seems it's not possible to do it with bluetooth L2CAP sockets
        # so, good old read fixed bytes way it is
        # 
        # we also split the data using \t because when a connection occurs, hosts send us messages from their
        # databases, they use more then one sock.send methods but we read them all at the same time
        datas = sock.recv(1023).split("\t")
        for data in datas:
            print "Data:[%s]\nSocket Type:[%s]\n" % (data, incoming_type)
            # parse the incoming data
            return self.data_parse(sock, data)
        

    def data_parse(self, sock, data):
        address = self.addresses[sock]              # incoming socket address
        incoming_type = self.get_socket_type(sock)  # again, we check the incoming type here too
        
        # if data length is greater than zero then process it, if not drop the connection
        # sockets somehow send empty messages when disconnecting
        if len(data) > 0:
            s_data = str(data)              # make data a string if not
            s_data_arr = s_data.split(",")  # and split using ,

            if not s_data_arr[0].isdigit():         # if first index is not a number (timestamp)
                name = s_data_arr[0]                # than it's the remote hostname
                if name not in self.hosts.keys():   # if we don't know them yet
                    self.hosts[name] = [0, 0]       # add it to our hosts dict
                if incoming_type == "wifi":         # and set the address accordingly
                    self.hosts[name][0] = address
                else:
                    self.hosts[name][1] = address

                if self.cleanup() == True:          # call the cleanup function, this removes bluetooth sockets if connected via wifi
                    return True                     # if it returns true, drop the connection here

                # print IRC style connection messages
                self.add_text("\n%s (%s) has joined." % (name, incoming_type))

                # self.discovered is not an array, append function adds people to the connections list in the GUI
                self.discovered.append ((address, name))
                
                # following lines gets the messages we have in our database for that host, and sends it to them
                rowc = 0
                rows = conn.execute("SELECT * FROM messages WHERE dest=\"" + s_data_arr[0] + "\"")
                for row in rows:
                    rowc += 1
                    sock.send(self.get_data(row[0], row[1], row[2], row[3]))
                    print self.get_data(row[0], row[1], row[2], row[3])
                    print "Queued message [%s] sent." % row[3]
                if rowc > 0:
                    conn.execute("DELETE FROM messages WHERE dest=\"" + s_data_arr[0] + "\"")
                    conn.commit()
                    print "Messages belonged to %s are removed from database." % s_data_arr[0]

                # incoming data was in the form of host,1 or host,2
                # host,1 means its discovery request, we send our hostname,2 to this kind of messages
                if s_data_arr[1] == "1":
                    sock.send(self.hostname + ",2\t")

                return True     # all is well

            # now that we know message is in the form of timestamp,host,dest,msg
            # we can process it
            mtime = datetime.datetime.fromtimestamp(int(s_data_arr[0]))     # get its time
            host = s_data_arr[1]                                            # host,
            dest = s_data_arr[2]                                            # destination
            message = ",".join(s_data_arr[3:])                              # and concat other indexes to get message

            # if we processed it before, drop it, if not add it to messages list
            if s_data not in self.messages:
                self.messages.append(s_data)
            else:
                return True

            # if message is sent to everybody or just us, print it on screen
            if dest == "" or dest == self.hostname:
                self.add_text("\n[%s] %s: %s" % (self.get_time(mtime), host, message))
                if dest == self.hostname: # if it's us, stop sending it to everyone
                    return True

            # if destination is not us but somebody
            if dest != "":
                # search that destination in our hosts, if found, send it to him/her
                if dest in self.hosts.keys():
                    if self.hosts[dest][0] != 0 and incoming_type != "wifi":
                        sock = self.peers[self.hosts[dest][0]]
                        sock.send(data + "\t")
                    else:
                        sock = self.peers[self.hosts[dest][1]]
                        sock.send(data + "\t")
                    print "Data sent to that host"
                    return True
                else: # if we don't see the host, queue the message
                    conn.execute("INSERT INTO messages VALUES (?, ?, ?, ?)", (int(s_data_arr[0]), host, dest, message))
                    print "Messaged added to queue"
                    conn.commit()

                self.messages.append(s_data)
                # also send it to everyone
                for hostKey in self.hosts.keys():
                    if hostKey == host:
                        continue
                    if self.hosts[hostKey][0] != 0:
                        sock = self.peers[self.hosts[hostKey][0]]
                        sock.send(s_data + "\t")
                    else:
                        sock = self.peers[self.hosts[hostKey][1]]
                        sock.send(s_data + "\t")
            else:
                # if message is meant to send to anyone, we printed it above, now it's time to send it
                self.messages.append(s_data)
                for hostKey in self.hosts.keys():
                    if hostKey == host:
                        continue
                    if self.hosts[hostKey][0] != 0:
                        sock = self.peers[self.hosts[hostKey][0]]
                        sock.send(s_data + "\t")
                    else:
                        sock = self.peers[self.hosts[hostKey][1]]
                        sock.send(s_data + "\t")

        else:
            # if data length is zero, drop the connection
            self.add_text("\n%s has quit. (ping timeout.)" % address)
            gobject.source_remove(self.sources[address])
            del self.sources[address]
            del self.peers[address]
            del self.addresses[sock]
            for row in self.discovered: # this is how you remove it from GTK tree view
                if row[0] == address:
                    self.discovered.remove(row.iter)
                    break
            sock.close()                # close the connection
            
        return True

# --- other stuff
    # returns socket type
    def get_socket_type(self, sock):
        socket_type = str(type(sock))
        if socket_type == "<class 'socket._socketobject'>":
            return "wifi"
        else:
            return "bluetooth"

    # removes bluetooth connections if connected via wifi
    def cleanup(self):
        for host in self.hosts.keys():
            if self.hosts[host][0] != 0 and self.hosts[host][1] != 0:
                sock = self.peers[self.hosts[host][1]]
                address = self.hosts[host][1]
                gobject.source_remove(self.sources[address])
                del self.sources[address]
                del self.peers[address]
                del self.addresses[sock]
                for row in self.discovered:
                    if row[0] == address:
                        self.discovered.remove(row.iter)
                        break
                print "%s has dropped because you are already connected via wifi" % host
                sock.close()
                return True

    # tries to connect over bluetooth
    def connect(self, addr, name):
        sock = bluetooth.BluetoothSocket (self.bluetoothConnType)
        sock.settimeout(self.timeout)
        try:
            sock.connect((addr, self.bluetoothPort))
            sock.send(self.hostname + ",1\t")
        except Exception as e:
            template = "An exception of type {0} occured. Arguments:{1!r}"
            mesg = template.format(type(e).__name__, e.args)
            print mesg
            sock.close()
            return

        self.peers[addr] = sock
        source = gobject.io_add_watch (sock, gobject.IO_IN, self.data_ready)
        self.sources[addr] = source
        self.addresses[sock] = addr

    # prints text to GUI
    def add_text(self, text):
        self.text_buffer.insert(self.text_buffer.get_end_iter(), text)

    # starts all listening sockets
    def start_server(self):
        self.server_sock = bluetooth.BluetoothSocket (self.bluetoothConnType)
        self.server_sock.bind(("",self.bluetoothPort))
        self.server_sock.listen(1)

        gobject.io_add_watch(self.server_sock, gobject.IO_IN, self.incoming_connection)

        if self.wifi:
            self.server_sock_wifi = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_sock_wifi.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_sock_wifi.bind((self.server_IP, 12345))
            self.server_sock_wifi.listen(5)

            gobject.io_add_watch(self.server_sock_wifi, gobject.IO_IN, self.incoming_connection_wifi)

    # run the GUI, start server etc
    def run(self):
        self.text_buffer.insert(self.text_buffer.get_end_iter(), "loading..")
        self.start_server()
        gtk.main()

    def discover(self, IP):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(10.0)

        server_address = (IP, self.wifi_port)
        try:
            sock.connect(server_address)
            sock.send(self.hostname + ",1\t")
            self.peers[IP] = sock
            source = gobject.io_add_watch (sock, gobject.IO_IN, self.data_ready)
            
            self.sources[IP] = source
            self.addresses[sock] = IP
        except Exception as e:
            template = "An exception of type {0} occured. Arguments:{1!r}"
            mesg = template.format(type(e).__name__, e.args)
            #print mesg

    def discover_bluetooth(self, addr, name):
        try:
            print "Trying to connect %s" %  name
            self.connect(addr, name)
        except Exception as e:
            template = "An exception of type {0} occured. Arguments:{1!r}"
            mesg = template.format(type(e).__name__, e.args)
            print mesg

if __name__ == "__main__":
    gui = BluezChatGui()
    gui.run()
