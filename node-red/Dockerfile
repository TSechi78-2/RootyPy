# Use the official Node-RED base image
FROM nodered/node-red:latest

# Set the working directory
WORKDIR /usr/src/node-red

# Copy settings file to the container
COPY settings.json /data/config.json

# Copy flows credentials file to the container
COPY flows.json /data/flows.json

# Install additional Node-RED nodes or other npm packages
# Replace <package_name> with the actual package names you want to install
RUN npm install \
    node-red-dashboard \
    node-red-contrib-python3-function
# Expose the Node-RED port
EXPOSE 1880

# Set the default command to start Node-RED
CMD ["npm", "start", "--", "--userDir", "/data"]