import { DynamoDB } from '@aws-sdk/client-dynamodb';

const dynamo = new DynamoDB();
const tableName = process.env.tableName;

export const handler = async (event, context) => {
    console.log('Event:', JSON.stringify(event));  

    
    const { userId, allowTime } = event;

    console.log('userId: ', userId)
    console.log('allowTime: ', allowTime)

    let queryParams = {
        TableName: tableName,
        KeyConditionExpression: "user_id = :userId and request_time > :allowTime",
        ExpressionAttributeValues: {
            ":userId": {'S': userId},
            ":allowTime": {'S': allowTime}
        }
    };
    
    try {
        let result = await dynamo.query(queryParams);
    
        console.log('History: ', JSON.stringify(result));    

        let history = [];
        for(let item of result.Items) {
            console.log('item: ', item);
            let request_time = item.request_time.S;
            let request_id = item.request_id.S;
            let body = item.body.S;
            let msg = item.msg.S;
            let type = item.type.S;

            history.push({
                'request_time': request_time,
                'request_id': request_id,
                'type': type,
                'body': body,
                'msg': msg,
            });
        }

        console.log('Json History: ', history);
        
        const response = {
            statusCode: 200,
            headers: {
                'Access-Control-Allow-Origin': 'http://127.0.0.1:5500',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'GET,OPTIONS'
            },
            msg: JSON.stringify(history)
        };
        return response;  
          
    } catch (error) {
        console.log(error);

        const response = {
            statusCode: 500,
            headers: {
                'Access-Control-Allow-Origin': 'http://127.0.0.1:5500',
                'Access-Control-Allow-Headers': 'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token',
                'Access-Control-Allow-Methods': 'GET,OPTIONS'
            },
            msg: error.toString()
        };
        return response;  
    } 
};